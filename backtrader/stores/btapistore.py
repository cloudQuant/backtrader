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
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, cast

from ..utils.coercion import coerce_float as _coerce_float
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
from .base_btapi_store import BaseBtApiStore
from .btapi_composition import (
    GatewayReadinessProof,
    LiveRunBinding,
    verify_run_binding,
)
from ._btapi_errors import (
    BtApiStoreError,
    LegacyGatewayMigrationRequiredError,
    LiveCompositionError,
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
from ..service.store_event_dispatch import (
    dispatch_store_sdk_event_locked as _dispatch_store_sdk_event_locked,
    dispatch_store_sdk_events_locked as _dispatch_store_sdk_events_locked,
    poll_store_sdk_events as _poll_store_sdk_events,
    preflight_store_sdk_event_batch as _preflight_store_sdk_event_batch,
    require_store_event_dispatch_contracts as _require_store_event_dispatch_contracts,
)
from ..execution.account_risk_state import (
    read_store_account_risk_snapshot as _read_store_account_risk_snapshot,
)
from ..service.bounded_metadata_probe import (
    run_store_metadata_probe as _run_store_metadata_probe,
)
from ..service.store_event_notifier import StoreEventNotifier
from ..service.store_event_batch import (
    StoreEventBatchCoordinator,
    StoreEventBatchError,
)
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
from ._contract_metadata import (
    StoreContractMetadataCache,
    bounded_metadata_probe_shutdown_proven as _bounded_metadata_probe_shutdown_proven,
    configure_bounded_metadata_probe_sdk_market_data_only,
    contract_metadata_aliases as _contract_metadata_aliases,
    verify_bounded_metadata_probe_sdk_market_data_only,
)
from ._latest_tick_cache import StoreLatestTickCache
from ._market_delivery_state import StoreMarketDeliveryState
from ._tick_stream_resync import TickStreamResyncPolicy

logger = get_logger(__name__)

_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()

# Iteration 65: the Store-owned SDK Execution routing composition. A strategy
# whose parsed service configuration selects routing owns one durable router
# over this SQLite file inside its own strategy state directory; the file is
# local-only, created once and reused across restarts.
EXECUTION_ROUTING_DB_FILENAME = "execution_routing.sqlite"
# The Gateway intent lifetime the router attaches to each persisted parent.
# The SDK accepts (0, 30]; nothing here derives it from account-wide values.
EXECUTION_ROUTING_TTL_SECONDS = 10.0


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


@dataclass(frozen=True)
class _CalendarStatusUnavailable:
    """Store-side failure; successful route observations stay SDK-owned."""

    status: str = "UNKNOWN"
    reason: str = "UNAVAILABLE"


@dataclass(frozen=True)
class _InstrumentStatusUnavailable:
    """Store-side failure of one status composition; it is never ``TRADABLE``.

    ``reason_code`` is one finite Store code.  The fields the direct-order gate
    reads mirror the SDK composition so both answers can be handled uniformly;
    nothing here is derived from a provider value or an account-wide default.
    """

    reason_code: str
    state: str = "UNKNOWN"
    session_phase: str = "UNKNOWN"
    observation_state: str = "UNKNOWN"
    calendar_state: str = "MISSING"
    calendar_reason: Optional[str] = None
    authorizes_trading: bool = False


def _safe_calendar_mixed_provenance(result, venue, kind, product, contract, trading_day):
    """Check query attribution consistency; digest shapes do not authenticate its source."""
    def exact(actual, expected):
        if type(actual) is not type(expected):
            return False
        if type(expected) is dict:
            return (set(actual) == set(expected)
                    and all(exact(actual[key], value) for key, value in expected.items()))
        return actual == expected

    provenance = result.simulation_provenance
    if (type(provenance) is not dict or set(provenance) != {
            "schema", "environment", "alignment", "target", "windows", "evidence_locator",
            "semantic_sha256", "evidence_sha256"}
            or provenance["schema"] != "bt_api.calendar-mixed-window-provenance/2"
            or provenance["environment"] != "SIMULATION_ONLY"
            or provenance["alignment"] != "REPEAT_OVER_MOCK_OWNER_DAY_MAPPING"):
        return False
    digest = r"[0-9a-f]{64}"
    if any(type(provenance[key]) is not str or re.fullmatch(digest, provenance[key]) is None
           for key in ("semantic_sha256", "evidence_sha256")):
        return False
    locator = provenance["evidence_locator"]
    if (type(locator) is not dict or set(locator) != {
            "candidate_id", "parent_candidate_id", "observation_id", "observation_run_id",
            "capture_id", "response_digest"}
            or any(type(locator[key]) is not str or re.fullmatch(r"[0-9a-f]{32}", locator[key]) is None
                   for key in ("candidate_id", "parent_candidate_id", "observation_id",
                               "observation_run_id"))
            or type(locator["capture_id"]) is not str
            or re.fullmatch(r"akshare\.capture\.[0-9a-f]{32}", locator["capture_id"]) is None
            or type(locator["response_digest"]) is not str
            or re.fullmatch(digest, locator["response_digest"]) is None):
        return False
    target = provenance["target"]
    if (type(target) is not dict or set(target) != {
            "venue", "kind", "product", "mock_contract", "valid_from", "valid_to"}
            or (target["venue"], target["kind"], target["product"], target["mock_contract"])
            != (venue, kind, product, contract)
            or kind != "future" or not contract.startswith("mock_")):
        return False
    try:
        first, last = (_dt.date.fromisoformat(target[key]) for key in ("valid_from", "valid_to"))
        if (any(type(target[key]) is not str or target[key] != value.isoformat()
                for key, value in (("valid_from", first), ("valid_to", last)))
                or not first <= trading_day <= last):
            return False
    except (TypeError, ValueError):
        return False
    rows = provenance["windows"]
    if (type(rows) is not list or len(rows) != len(result.windows)
            or not {"AKSHARE.simulation_unverified", "MOCK.simulation_only"} <= set(result.source_ids)):
        return False
    windows = {window.window_id: window for window in result.windows}
    if len(windows) != len(result.windows):
        return False
    seen = set()
    for row in rows:
        if (type(row) is not dict or set(row) != {
                "scope", "window_id", "source_type", "fields", "observation", "simulation"}
                or type(row["window_id"]) is not str or row["window_id"] in seen
                or row["window_id"] not in windows or row["scope"] not in ("DAY", "NIGHT")
                or row["source_type"] not in ("AKSHARE", "MOCK")):
            return False
        seen.add(row["window_id"])
        window = windows[row["window_id"]]
        offset = (window.end_local.date() - window.start_local.date()).days
        if (offset not in (0, 1)
                or (row["scope"] == "DAY"
                    and (offset != 0 or window.start_local.date() != trading_day))
                or (row["scope"] == "NIGHT" and window.start_local.date() >= trading_day)):
            return False
        basis = "AKSHARE_SYNTAX_CANDIDATE" if row["source_type"] == "AKSHARE" else "MOCK_ASSUMPTION"
        transition = (("EXPLICIT_NEXT_DAY" if offset else "SAME_CLOCK_DAY")
                      if row["source_type"] == "AKSHARE" else offset)
        if (not exact(row["fields"], {
                "scope": {"value": row["scope"], "basis": basis},
                "start": {"value": window.start_local.strftime("%H:%M"), "basis": basis},
                "end": {"value": window.end_local.strftime("%H:%M"), "basis": basis},
                "day_transition": {"value": transition, "basis": basis}})
                or window.start_local.second or window.start_local.microsecond
                or window.end_local.second or window.end_local.microsecond
                or not exact(row["observation"], dict.fromkeys(
                    ("phase", "identity", "effective_period", "trading_day", "coverage"), "UNKNOWN"))
                or not exact(row["simulation"], {
                    "phase": {"value": window.phase, "basis": "MOCK_ASSUMPTION"},
                    "timezone": {"value": "Asia/Shanghai", "basis": "MOCK_ASSUMPTION"},
                    "local_date": {"value": "UNKNOWN", "basis": "UNKNOWN"},
                    "trading_day": {"value": "UNKNOWN", "basis": "UNKNOWN"},
                    "night_ownership": {"value": "UNKNOWN", "basis": "UNKNOWN"}})):
            return False
    return seen == set(windows)


def _safe_calendar_observation(value, status_type):
    """Accept only the SDK's bounded public status vocabulary and identifiers."""
    if type(value) is not status_type:
        return False
    enums = {
        "status": {"UNKNOWN", "OBSERVED_UNAUTHENTICATED"},
        "reason": {"INVALID_ROUTE", "ROUTE_UNCONFIGURED", "CURRENT_UNAVAILABLE",
                   "CONFIGURATION_CHANGED", "CURRENT_RECEIPTS_CONSISTENT"},
        "published": {"UNKNOWN", "CURRENT_OBSERVED"},
        "coverage_status": {"UNKNOWN", "NOT_PRESENT", "DECLARED_UNVERIFIED"},
        "bound": {"NOT_BOUND"},
        "binding_reason": {"RUNTIME_BINDING_NOT_IMPLEMENTED"},
        "source_authentication": {"NOT_PROVEN"},
        "identity_authentication": {"NOT_PROVEN"},
        "route_mapping": {"CALLER_DECLARED_ONLY"},
        "publication_authentication": {"NOT_PROVEN"},
        "durability": {"UNCONFIRMED"},
        "observation": {"CURRENT_NOT_PINNED"},
    }
    if any(type(getattr(value, field)) is not str or getattr(value, field) not in choices
           for field, choices in enums.items()):
        return False
    for field in ("publication_id", "version_id"):
        field_value = getattr(value, field)
        if field_value is not None and (
            type(field_value) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", field_value) is None
        ):
            return False
    for field in ("publication_sha256", "content_sha256"):
        field_value = getattr(value, field)
        if field_value is not None and (
            type(field_value) is not str or re.fullmatch(r"[0-9a-f]{64}", field_value) is None
        ):
            return False
    identity_fields = (value.publication_id, value.version_id,
                       value.publication_sha256, value.content_sha256)
    if value.status == "OBSERVED_UNAUTHENTICATED":
        return (value.reason == "CURRENT_RECEIPTS_CONSISTENT"
                and value.published == "CURRENT_OBSERVED"
                and value.coverage_status in {"NOT_PRESENT", "DECLARED_UNVERIFIED"}
                and all(field is not None for field in identity_fields))
    return (value.reason in {"INVALID_ROUTE", "ROUTE_UNCONFIGURED", "CURRENT_UNAVAILABLE",
                             "CONFIGURATION_CHANGED"}
            and value.published == "UNKNOWN" and value.coverage_status == "UNKNOWN"
            and all(field is None for field in identity_fields))


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


class BtApiStore(StoreManagedExecutionBridgeMixin, StoreReconciliationBridgeMixin, BaseBtApiStore):
    """Backtrader lifecycle and projection facade over the bt_api_py API."""

    BrokerCls = None
    DataCls = None

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
        gateway_host: Any = None,
        gateway_security_profiles: Any = None,
        gateway_run_lock: Any = None,
        calendar_config_file: Any = None,
        calendar_config: Any = None,
        calendar_ctp_routes: Any = None,
        service_client_config: Any = None,
        gateway_client_config: Any = None,
        execution_parent_port: Any = None,
        run_binding: Optional[LiveRunBinding] = None,
        gateway_readiness_proof: Optional[GatewayReadinessProof] = None,
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
                clean source epoch after any bar loss. A ``gateway_strategy``
                mapping explicitly selects the independent Gateway client;
                its public fields follow SDK ``GatewayStrategyConfig``.
            preserve_raw_bars: Preserve raw bar fields for strict opt-in consumers.
            contract_metadata: Contract metadata by symbol.
            backend: Legacy runtime backend selector. Only ``direct`` is
                supported; the independent Gateway uses ``gateway_strategy``
                in config, not a retired backend alias.
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
            gateway_host: Explicit strategy-local Gateway pending host. Its
                durable identity must match the Gateway configuration.
            gateway_security_profiles: Separately resolved SDK CURVE keys, not
                embedded in the public configuration mapping.
            gateway_run_lock: Reserved; externally held locks are rejected
                because their process ownership cannot currently be verified.
            calendar_config_file: Absolute path of the parsed configuration file.
            calendar_config: Parsed mapping containing the explicit calendars section.
            calendar_ctp_routes: Caller-declared exact CTP routes for status only.
                These configure a Store-local reader, not the SDK facade or trading.
            service_client_config: Optional already-parsed SDK strategy-client
                ``ClientConfig`` (``parse_client_config``). Only a configuration
                whose Execution block carries ``execution_routing`` selects the
                Iteration 65 composition; anything else, and every partial input
                set, is refused with a finite code.
            gateway_client_config: Optional already-parsed SDK
                ``GatewayStrategyConfig`` naming this strategy's exact Gateway
                binding and route. Supplying it together with
                ``service_client_config`` and ``execution_parent_port`` selects
                the Execution routing composition; the three must agree on the
                account, strategy and direct-write route. The object grants no
                authority by itself and starts no Execution service.
            execution_parent_port: Optional injected Execution
                ``service.execution_parent`` port of the trusted service runtime
                (an object with callable ``submit`` and, optionally, ``cancel``).
                It is passed unchanged to the SDK router and is never built,
                discovered or faked by the Store. Without it a routing selection
                is refused rather than replaced by an in-process service.
            **kwargs: Additional SDK configuration values.
                ``event_batch_handoff=True`` is an explicit, irreversible
                single-route opt-in. It uses the SDK's process-local
                poll/dispatch/ACK lease and never falls back to legacy polling;
                because this SDK exposes no producer-quiescence receipt,
                ``stop()`` remains INCOMPLETE and retains the API/waker after
                the claim.
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
        # D64-01/U64-5: Risk exists only with the Gateway and is selected only
        # inside gateway_strategy (parsed by the SDK). Any other risk key is
        # refused before merging sources, where one section could hide another.
        try:
            # Inspect and later consume the same snapshots. A lazy Mapping may
            # otherwise change between membership checks and dict conversion.
            snapshots = []
            for source in (config, api_kwargs, kwargs):
                snapshot = dict(source) if source is not None else {}
                for section_name in ("gateway", "gateway_strategy"):
                    section = snapshot.get(section_name)
                    if isinstance(section, Mapping):
                        snapshot[section_name] = dict(section)
                snapshots.append(snapshot)
            config, api_kwargs, kwargs = snapshots
            self._gateway_mode = "gateway_strategy" in config
            gateway_tree = config.get("gateway_strategy") if self._gateway_mode else None
            misplaced_risk = False
            for index, source in enumerate((config, api_kwargs, kwargs)):
                if "risk" in source:
                    misplaced_risk = True
                    break
                for section_name in ("gateway", "gateway_strategy"):
                    # Only config.gateway_strategy is the selected Gateway
                    # configuration; its risk selection belongs to the SDK.
                    if index == 0 and self._gateway_mode and section_name == "gateway_strategy":
                        continue
                    if section_name in source:
                        section = source[section_name]
                        if isinstance(section, Mapping) and "risk" in section:
                            misplaced_risk = True
                            break
                if misplaced_risk:
                    break
        except Exception:
            error = BtApiStoreError("risk_selection_invalid")
            error.code = "risk_selection_invalid"
            raise error from None
        if misplaced_risk:
            code = "risk_selection_invalid" if self._gateway_mode else "risk_requires_gateway"
            error = BtApiStoreError(code)
            error.code = code
            raise error
        self._gateway_pid = os.getpid() if self._gateway_mode else None
        self._gateway_strategy_config = None
        self._gateway_host = None
        self._gateway_security_profiles = None
        self._gateway_run_lock = None
        self._gateway_owns_run_lock = False
        self._gateway_execution_db = None
        self._gateway_composition_uncertain = False
        self._gateway_composition_cleanup_owner = None
        self._gateway_composition_binding = None
        self._gateway_state = None
        self._gateway_closed = False
        self._gateway_start_attempted = False
        self._gateway_reconnect_next = 0.0
        self._gateway_reconnect_attempt = 0
        self._gateway_reconnect_reason = None
        self._gateway_session_generation = 0
        self._gateway_readiness_proof: Optional[GatewayReadinessProof] = None
        if run_binding is not None:
            if not isinstance(run_binding, LiveRunBinding):
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="invalid_run_binding")
            expected_mode = "gateway" if self._gateway_mode else "direct"
            if run_binding.mode != expected_mode:
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="store_mode_mismatch")
            self._run_binding = run_binding
        if gateway_readiness_proof is not None:
            if not self._gateway_mode:
                raise LiveCompositionError("MODE_CONFLICT", detail="gateway_readiness_proof")
            if not isinstance(gateway_readiness_proof, GatewayReadinessProof):
                raise LiveCompositionError(
                    "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="invalid_proof_type"
                )
            self._gateway_readiness_proof = gateway_readiness_proof
        if self._gateway_mode:
            from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config
            from ..live_state.gateway_pending import GatewayPendingHost
            from ..live_state.state_dir import StrategyStateDir

            if (self.provider != "btapi" or backend not in (None, "") or api is not None
                    or api_cls is not None or managed_execution_adapter is not None
                    or execution_authorization is not None or settlement_authorization is not None
                    or api_kwargs or kwargs or type(gateway_host) is not GatewayPendingHost
                    or not isinstance(gateway_security_profiles, Mapping)
                    or not gateway_security_profiles):
                raise BtApiStoreError("GATEWAY_CONFIGURATION_CONFLICT")
            self._gateway_strategy_config = parse_gateway_strategy_config(gateway_tree)
            if gateway_host._binding != self._gateway_strategy_config.binding:
                raise BtApiStoreError("GATEWAY_HOST_BINDING_MISMATCH")
            self._gateway_host = gateway_host
            self._gateway_security_profiles = dict(gateway_security_profiles)
            state = StrategyStateDir(gateway_host._store.paths.strategy_dir)
            if state.strategy_uuid != gateway_host._store.strategy_uuid:
                raise BtApiStoreError("GATEWAY_HOST_IDENTITY_MISMATCH")
            if gateway_run_lock is not None:
                raise BtApiStoreError("GATEWAY_BORROWED_LOCK_UNSUPPORTED")
            self._gateway_state = state
            self.backend = "gateway_strategy"
        elif gateway_host is not None or gateway_security_profiles is not None or gateway_run_lock is not None:
            raise BtApiStoreError("GATEWAY_CONFIGURATION_REQUIRED")
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
        self._config = config
        self._api_kwargs = api_kwargs
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
        event_batch_handoff = sdk_options.get("event_batch_handoff", False)
        if type(event_batch_handoff) is not bool:
            raise BtApiStoreError("event_batch_handoff must be a boolean")
        self._sdk_event_batch_handoff = event_batch_handoff
        if self._sdk_event_batch_handoff and not self._sdk_mode:
            raise BtApiStoreError("event_batch_handoff requires direct SDK mode")
        self._service_read_only_stopped = False
        # Iteration 62 (D62-01/I62-08): the SDK direct write path is selected
        # when write admission is enabled for a route and no optional execution
        # component is configured.  Admission stays the SDK's decision; this
        # flag only tells BtApiBroker which framework path to run.
        from bt_api_py.direct_api_assembly import DIRECT_EXECUTION_CONFIG_KEYS as _exec_keys

        admission_config = sdk_options.get("write_admission")
        self._direct_write_routes = (
            frozenset(str(name) for name, enabled in admission_config.items() if enabled is True)
            if isinstance(admission_config, Mapping)
            else frozenset()
        )
        has_execution = "execution_config" in sdk_options or any(
            key in sdk_options for key in _exec_keys
        )
        if self._sdk_event_batch_handoff and has_execution:
            # The SDK refuses the irreversible queue claim while an execution
            # session owns event reconciliation. Reject this configuration
            # before a Store factory or any consumer registration attempt.
            raise BtApiStoreError(
                "event_batch_handoff is unavailable with execution configuration"
            )
        self._direct_write_mode = bool(
            self._sdk_mode
            and not self._service_read_only
            and self._direct_write_routes
            and not has_execution
        )
        configured_exchanges = sdk_options.get("exchange_kwargs")
        if self._gateway_mode:
            if (configured_exchanges is not None or "write_admission" in sdk_options
                    or has_execution):
                raise BtApiStoreError("GATEWAY_CONFIGURATION_CONFLICT")
            self._sdk_direct_exchange_kwargs = None
            self._sdk_exchanges = {self._gateway_strategy_config.exchange_name: {}}
        elif isinstance(configured_exchanges, Mapping):
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
        if self._sdk_event_batch_handoff and len(self._sdk_exchanges) != 1:
            # Consumer registration cannot be rolled back per route. Restrict
            # this opt-in to one route so registration is atomic at Store scope.
            raise BtApiStoreError("event_batch_handoff requires exactly one route")
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
        self._calendar_local_reader = None
        self._calendar_local_routes = frozenset()
        # D67-01: routes whose local reader was installed from the in-package
        # seed.  Status reports label them so they are never mistaken for a
        # daily-updated external directory.
        self._calendar_package_seed_routes = frozenset()
        # Route roots to mirror into a Store-owned facade (G8).  A borrowed or
        # caller-constructed facade is never rewritten.
        self._calendar_facade_route_roots = None
        self._calendar_facade_configuration = "PENDING"
        self._calendar_facade_attempted_api = None
        # Explicit read-only instrument-status source (iteration 67.06).  It is
        # never discovered or constructed here and performs no I/O by itself.
        self._instrument_status_port = None
        # Route-scoped ports attached by the Store itself from the configured
        # direct provider (G3).  A route without a port keeps its gate inert.
        self._instrument_status_ports: Dict[str, Any] = {}
        self._instrument_status_ports_bound_for = None
        if any(value is not None for value in (
            calendar_config_file, calendar_config, calendar_ctp_routes
        )):
            if self._gateway_mode or self._service_read_only or not self._sdk_mode:
                raise BtApiStoreError("calendar_configuration_requires_direct_sdk")
            from ..service.trading_calendar_config import parse_direct_calendar_status
            try:
                candidate, route_roots = parse_direct_calendar_status(
                    calendar_config, config_file=calendar_config_file,
                    ctp_routes=calendar_ctp_routes, configured_routes=set(self._sdk_exchanges),
                    package_seed_binding=True,
                )
            except Exception:
                raise BtApiStoreError("calendar_configuration_invalid") from None
            if candidate.root_kind == "package_seed":
                seed_root = self._install_package_calendar_seed(calendar_config_file)
                route_roots = {route: str(seed_root) for route in calendar_ctp_routes}
            if candidate.root_kind in ("directory", "package_seed"):
                try:
                    from bt_api_py.trading_calendar_runtime_status import TradingCalendarStatusReader
                    reader = TradingCalendarStatusReader()
                    reader.configure(route_roots)
                except Exception:
                    raise BtApiStoreError("calendar_status_configuration_failed") from None
                self._calendar_local_reader = reader
                self._calendar_local_routes = frozenset(route_roots)
                self._calendar_facade_route_roots = dict(route_roots)
                if candidate.root_kind == "package_seed":
                    self._calendar_package_seed_routes = frozenset(route_roots)
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
        # Iteration 65: validate (but do not compose) the optional Execution
        # routing selection. Composition needs the strategy directory, which
        # only the Broker knows, so it happens in ``start``.
        self._configure_execution_routing(
            service_client_config, gateway_client_config, execution_parent_port
        )
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
        # Iteration 62 continuity-7: when the Store acknowledges a provider-
        # declared tick-stream restart by itself (PROVIDER_RESYNC_REQUIRED);
        # direct provider streams only, never Gateway market runtime ticks.
        self._tick_stream_resync = TickStreamResyncPolicy(
            enabled=sdk_options.get("market_runtime_factory") is None
        )
        # D62-38 point 7: why an SDK tick channel delivers nothing (its last
        # polled result was not ACTIVE), so a Feed can leave LIVE meanwhile.
        self._tick_stream_recovery: Dict[str, str] = {}
        self._stream_generation = 0
        self._has_successful_sdk_stream_generation = False
        self._sdk_borrowed_event_source_retired = False
        self._sdk_start_state_lock = threading.Condition(threading.Lock())
        self._sdk_start_in_progress = False
        self._sdk_start_owner_thread_id = None
        self._sdk_stop_in_progress = False
        self._sdk_stop_pending_broker_updates = False
        self._sdk_stop_command_worker_unproven = False
        self._sdk_event_drain_in_progress = False
        self._sdk_event_drain_owner_thread_id = None
        self._sdk_api_activity_count = 0
        self._sdk_api_activity_threads: Dict[int, int] = {}
        self._sdk_partial_start_failed_generation = None
        self._sdk_event_batch_size = max(int(sdk_options.get("event_batch_size", 1024)), 1)
        self._sdk_event_batch_event_limit = min(self._sdk_event_batch_size, 1024)
        self._sdk_event_batch_scan_limit = 256
        self._sdk_event_batch_coordinator = None
        self._sdk_event_batch_claim_lock = threading.Lock()
        self._sdk_event_batch_continuation_pending = False
        self._sdk_event_batch_stop_requested = False
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
        self._calendar_status_lock = threading.Lock()
        self._calendar_status_generation = 0
        self._calendar_status_transitions = 0
        self._calendar_status_stopping = False
        from bt_api_py.bounded_metadata_probe import BoundedMetadataProbeService

        self._metadata_probe_service = BoundedMetadataProbeService(
            worker_name="BtApiStoreReadOnlyMetadataProbe"
        )
        self._data_feeds: list = []
        self._tick_consumers: Dict[str, Any] = {}
        self._latest_tick_cache = StoreLatestTickCache(
            snapshot_tick=_snapshot_tick,
            aliases_for=_contract_metadata_aliases,
        )
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
        if self._gateway_mode:
            from ..service.gateway_config import compose_gateway_contract_metadata

            self.contract_metadata = compose_gateway_contract_metadata(
                self._gateway_strategy_config, self._config.get("contracts"),
                contract_metadata, BtApiStoreError,
            )
        else:
            self.contract_metadata = {
                str(key): dict(value or {}) for key, value in (contract_metadata or {}).items()
            }
        self._contract_metadata_cache = StoreContractMetadataCache(
            mapping_getter=lambda: self.contract_metadata,
        )
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

    # ------------------------------------------------------------------
    # Path 5 (Direct+Execution hybrid routing) retired by Iteration 62 Split (D62S-07).
    # Read-only export of legacy state/execution_routing.sqlite lives in
    # backtrader.live_state.legacy_export / CLI `export-legacy-execution-routing`.
    # ------------------------------------------------------------------
    def _configure_execution_routing(
        self,
        service_client_config: Any,
        gateway_client_config: Any,
        execution_parent_port: Any,
    ) -> None:
        self._execution_parent_port = None
        self._execution_routing_client_config = None
        self._execution_routing_public_config = None
        self._execution_routing_gateway_config = None
        self._execution_routing_selected = False
        self._execution_routing_selection = None
        self._execution_routing_connection = None
        self._execution_routing_db_path = None
        self._execution_routing_state_dir = None
        if (
            service_client_config is not None
            or gateway_client_config is not None
            or execution_parent_port is not None
        ):
            raise LiveCompositionError(
                "LEGACY_HYBRID_ROUTING_RETIRED",
                detail="direct_execution_hybrid_routing_retired",
            )

    @property
    def execution_routing_selection(self) -> Any:
        """Retired path 5 selection; always ``None`` on BtApiStore."""
        return None

    @property
    def execution_routing_db_path(self) -> Optional[str]:
        """Retired path 5 DB path; always ``None`` on BtApiStore."""
        return None

    @property
    def is_connected(self) -> bool:
        """Return whether the store is connected and ready."""
        if self._gateway_mode:
            if (self._gateway_pid != os.getpid() or not self._connected or self._api is None
                    or self._gateway_run_lock is None
                    or not self._gateway_run_lock.held):
                return False
            status = self._api.status()
            return status.state == "running" and status.healthy is True
        return self._connected

    def gateway_session_state(self) -> str:
        """Gateway mode only: ``CONNECTED``, ``UNAVAILABLE`` or ``LOST``.

        ``UNAVAILABLE`` is a live SDK session that is momentarily not healthy
        (for example while the Gateway is paused or restarting); it may come
        back by itself. ``LOST`` means this SDK session cannot: the Store
        stopped or lost its run lock, or the SDK runtime failed or closed
        (I63-E112). While the Store is still running
        (:meth:`gateway_session_recoverable`), a lost session is replaced by a
        new registration with :meth:`gateway_reconnect` (D63-03).
        """
        if not self._gateway_mode:
            raise RuntimeError("GATEWAY_MODE_REQUIRED")
        if (self._gateway_pid != os.getpid() or not self._connected or self._api is None
                or self._gateway_run_lock is None
                or not self._gateway_run_lock.held):
            return "LOST"
        status = self._api.status()
        if status.state == "running" and status.healthy is True:
            return "CONNECTED"
        if status.state in ("starting", "running") and status.thread_alive is True:
            return "UNAVAILABLE"
        return "LOST"

    def gateway_session_recoverable(self) -> bool:
        """Gateway mode only: the Store still runs, so a lost session may be replaced."""
        if not self._gateway_mode:
            raise RuntimeError("GATEWAY_MODE_REQUIRED")
        from ..service.gateway_config import gateway_session_recoverable

        return gateway_session_recoverable(self)

    def gateway_reconnect(self, timeout: Optional[float] = None) -> bool:
        """Gateway mode only: register a new SDK session after the old one was lost.

        Returns ``True`` once a healthy session is installed, ``False`` while
        the caller has to keep waiting (D63-03). Bound objects must then adopt
        :attr:`gateway_api`; nothing is retried or re-sent by this call.
        """
        if not self._gateway_mode:
            raise RuntimeError("GATEWAY_MODE_REQUIRED")
        from ..service.gateway_config import reconnect_gateway_store

        return reconnect_gateway_store(self, timeout=timeout)

    @property
    def gateway_session_generation(self) -> int:
        """Number of SDK sessions this Store re-registered after the first one."""
        return self._gateway_session_generation

    @property
    def uses_async_commands(self) -> bool:
        """Whether this SDK facade exposes the typed asynchronous command contract.

        Restored in iteration 60: the iteration-53 split removed the property
        while ``store_lifecycle``, ``store_event_dispatch``, the reconciliation
        bridge and ``BtApiBroker`` still read it, so every SDK-mode start
        failed with ``AttributeError`` and the Broker silently treated SDK
        Stores as synchronous.
        """
        import inspect

        api = self._api
        return bool(
            self._sdk_mode
            and api is not None
            and all(
                inspect.iscoroutinefunction(getattr(api, name, None))
                for name in ("async_make_order", "async_cancel_order", "async_query_order")
            )
        )

    @property
    def direct_write_mode(self) -> bool:
        """True when BtApiBroker must run the SDK direct write path (iteration 62)."""
        return bool(getattr(self, "_direct_write_mode", False))

    @property
    def sdk_api(self) -> Any:
        """Return no raw API for retired gateway/forwarding routes.

        Store query methods continue to use the managed client internally.
        """
        if self._gateway_mode or _legacy_gateway_entrypoint(self.provider, self.backend) is not None:
            return None
        return self._api

    @property
    def gateway_api(self):
        """Gateway facade after explicit Store startup, or None before startup."""
        return self._api if self._gateway_mode else None

    @property
    def gateway_host(self):
        """Borrowed strategy-local pending host; never owned or closed by Store."""
        return self._gateway_host

    @property
    def gateway_strategy_config(self):
        """Detached public Gateway configuration selected for this Store."""
        return self._gateway_strategy_config

    @property
    def gateway_sequence(self):
        """Sequence bound to the Gateway host's strategy state."""
        return None if self._gateway_state is None else self._gateway_state.sequence

    def bind_gateway_strategy(self, strategy, *, data_by_ref, sequence=None, orders_by_key=None,
                              page_limit=128, timeout_seconds=1.0):
        """Bind the existing broker after Strategy and Feed objects exist.

        Store holds the existing run lock; the sequence must name the same
        strategy state. This does not infer account readiness or create a
        second strategy lifecycle.
        """
        if not self._gateway_mode or not self._started or not self.is_connected:
            raise BtApiStoreError("GATEWAY_SESSION_UNAVAILABLE")
        broker = self._broker
        bind = getattr(broker, "bind_gateway_execution_stream", None)
        if broker is None or getattr(strategy, "broker", None) is not broker or not callable(bind):
            raise BtApiStoreError("GATEWAY_BROKER_BINDING_INVALID")
        if sequence is None:
            sequence = self.gateway_sequence
        if (sequence is not self.gateway_sequence
                and (getattr(sequence, "strategy_uuid", None) != self._gateway_state.strategy_uuid
                     or getattr(getattr(sequence, "paths", None), "sequence", None)
                     != self._gateway_state.paths.sequence)):
            raise BtApiStoreError("GATEWAY_SEQUENCE_BINDING_INVALID")
        if orders_by_key is None:
            orders_by_key = {}
        return bind(strategy, api=self._api, host=self._gateway_host,
                    data_by_ref=data_by_ref, orders_by_key=orders_by_key,
                    instrument_by_ref=dict(self._gateway_strategy_config.instruments_by_ref),
                    time_policy=self._gateway_strategy_config.execution_time_policy,
                    sequence=sequence, page_limit=page_limit, timeout_seconds=timeout_seconds)

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

    @property
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
        owns_start_slot = False
        if self._sdk_mode or self._service_read_only:
            with self._sdk_start_state_lock:
                if self._service_read_only_stopped:
                    raise BtApiStoreError(
                        "a stopped read-only service Store requires fresh client facades"
                    )
                if self._sdk_mode and self._sdk_partial_start_failed_generation is not None:
                    raise BtApiStoreError(
                        "store_partial_sdk_start_requires_verified_stop"
                    )
                if self._sdk_stop_in_progress:
                    raise BtApiStoreError(
                        "store_sdk_stop_already_in_progress"
                        if self._sdk_mode
                        else "store_service_stop_already_in_progress"
                    )
                if self._sdk_mode and self._sdk_stop_command_worker_unproven:
                    raise BtApiStoreError(
                        "store_sdk_command_worker_shutdown_unproven"
                    )
                if self._sdk_mode and self._sdk_event_batch_stop_requested:
                    raise BtApiStoreError(
                        "store_sdk_event_batch_producer_quiescence_unproven"
                    )
                if self._sdk_mode:
                    coordinator = self._sdk_event_batch_coordinator
                    if coordinator is not None and coordinator.state not in {
                        "new",
                        "claimed",
                        "claim_blocked",
                    }:
                        raise BtApiStoreError(
                            "store_sdk_event_batch_consumer_unavailable"
                        )
                if self._sdk_mode and self._sdk_stop_pending_broker_updates:
                    raise BtApiStoreError(
                        "store_sdk_broker_update_handoff_blocked"
                    )
                if self._sdk_start_in_progress:
                    raise BtApiStoreError(
                        "store_sdk_start_already_in_progress"
                        if self._sdk_mode
                        else "store_service_start_already_in_progress"
                    )
                if self._sdk_mode and self._sdk_event_drain_in_progress:
                    raise BtApiStoreError("store_sdk_event_drain_in_progress")
                if self._sdk_api_activity_count:
                    raise BtApiStoreError(
                        "store_sdk_api_activity_in_progress"
                        if self._sdk_mode
                        else "store_service_api_activity_in_progress"
                    )
                if self._sdk_mode:
                    borrowed_event_error = self._sdk_borrowed_event_lifecycle_error()
                    if borrowed_event_error is not None:
                        raise BtApiStoreError(borrowed_event_error)
                self._sdk_start_in_progress = True
                self._sdk_start_owner_thread_id = threading.get_ident()
                self._sdk_start_state_lock.notify_all()
                owns_start_slot = True
        previous_stream_generation = self._stream_generation
        started = False
        transition_generation = None
        try:
            with self._calendar_status_lock:
                self._calendar_status_generation += 1
                transition_generation = self._calendar_status_generation
                self._calendar_status_transitions += 1
                self._calendar_status_stopping = True
            result = _start_store(
                self, data, broker, error_type=BtApiStoreError,
                gateway_entrypoint=_legacy_gateway_entrypoint,
                gateway_error_type=LegacyGatewayMigrationRequiredError,
            )
            if self._sdk_mode:
                # Commit the successful-start boundary only after API setup,
                # worker setup, and the Store lifecycle bridge all return.
                with self._sdk_event_drain_lock:
                    self._live_bar_queue.commit_generation(self._stream_generation)
                    self._has_successful_sdk_stream_generation = True
            started = True
            return result
        except BaseException:
            if (
                self._sdk_mode
                and self._stream_generation != previous_stream_generation
            ):
                failed_generation = self._stream_generation
                with self._sdk_event_drain_lock:
                    symbols, removed = self._live_bar_queue.discard_generation(
                        failed_generation
                    )
                if self._sdk_partial_start_requires_verified_stop():
                    with self._sdk_start_state_lock:
                        self._sdk_partial_start_failed_generation = failed_generation
                        if (
                            not self._sdk_owned_api
                            and self._managed_runtime_borrowed_api is None
                            and not self._service_read_only
                        ):
                            # A partial attempt that reached Store-owned
                            # resources may have crossed an SDK source boundary.
                            # A verified Store stop cannot prove or clear the
                            # caller-owned facade's queued event generation.
                            self._sdk_borrowed_event_source_retired = True
                for symbol, bar in removed:
                    self._record_market_drop(
                        bar,
                        "store_live_bar_start_aborted",
                        safety_impact="bar_discarded_after_partial_store_start",
                        symbol=symbol,
                        kind="bar",
                    )
                for symbol in symbols:
                    self._mark_live_bar_queue_stale(
                        symbol, "store_live_bar_start_aborted"
                    )
            raise
        finally:
            if owns_start_slot:
                with self._sdk_start_state_lock:
                    self._sdk_start_in_progress = False
                    self._sdk_start_owner_thread_id = None
            if transition_generation is not None:
                with self._calendar_status_lock:
                    self._calendar_status_transitions -= 1
                    if (
                        started
                        and self._calendar_status_generation == transition_generation
                    ):
                        self._calendar_status_stopping = False

    def _sdk_partial_start_requires_verified_stop(self) -> bool:
        """Return whether an aborted SDK start still owns running resources."""
        if (
            self._started
            or self._connected
            or self._market_stream_adapter.has_subscriptions
            or self._restart_blocked_by_close
            or self._sdk_close_thread is not None
            or self._sdk_api_close_state is not None
            or (self._sdk_owned_api and self._api is not None)
            or self._managed_runtime_borrowed_api is not None
        ):
            return True
        try:
            command_state = self._command_runtime.snapshot()
            if command_state.worker_alive or command_state.has_active_work:
                return True
            funding_health = self.get_funding_refresh_health()
        except Exception:
            # A failed health read cannot prove that a partially initialized
            # Store is safe to start again.
            return True
        return bool(funding_health.get("worker_alive") or funding_health.get("inflight"))

    @staticmethod
    def _bounded_metadata_probe_shutdown_proven(health: Any) -> bool:
        """Return whether a one-shot probe has no live Store work left behind."""
        return _bounded_metadata_probe_shutdown_proven(health)

    def _configure_bounded_metadata_probe_sdk_market_data_only(self) -> None:
        """Require the SDK assembly to apply the probe's zero-write settings."""
        return configure_bounded_metadata_probe_sdk_market_data_only(
            self,
            error_type=BtApiStoreError,
            safe_log=_safe_log,
        )

    def _verify_bounded_metadata_probe_sdk_market_data_only(self) -> None:
        """Require public SDK state after every probe lifecycle transition."""
        return verify_bounded_metadata_probe_sdk_market_data_only(
            self,
            error_type=BtApiStoreError,
            missing_dependency_error_type=BtApiMissingDependencyError,
            safe_log=_safe_log,
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
        """Reset Store-owned event projections before starting an SDK generation."""
        reset_thread_id = threading.get_ident()
        owns_start_slot = False
        with self._sdk_start_state_lock:
            if self._sdk_event_drain_in_progress:
                raise BtApiStoreError("store_sdk_event_drain_in_progress")
            if self._sdk_api_activity_count:
                raise BtApiStoreError("store_sdk_api_activity_in_progress")
            if self._sdk_stop_in_progress:
                raise BtApiStoreError("store_sdk_stop_already_in_progress")
            if self._sdk_start_in_progress:
                if self._sdk_start_owner_thread_id != reset_thread_id:
                    raise BtApiStoreError("store_sdk_start_already_in_progress")
            else:
                # Private callers still use the same short transition slot so
                # a new Store poll cannot begin between the check and reset.
                self._sdk_start_in_progress = True
                self._sdk_start_owner_thread_id = reset_thread_id
                owns_start_slot = True
        try:
            with self._sdk_event_drain_lock:
                has_prior_generation = self._has_successful_sdk_stream_generation
                self._stream_generation += 1
                self._account_risk_state.reset_generation()
                self._sdk_execution_identity_fence.clear_session()
                self._market_delivery_state.reset_generation()
                # Constructor-supplied live_bars belong to the first generation.
                # Only a restart has a prior Store generation whose queued bars
                # and sticky loss state must be discarded.
                if has_prior_generation:
                    self._live_bar_queue.reset()
                self._tick_stream_resync.reset()
                self._tick_stream_recovery.clear()
        finally:
            if owns_start_slot:
                with self._sdk_start_state_lock:
                    self._sdk_start_in_progress = False
                    self._sdk_start_owner_thread_id = None

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
        """Finish only a Store-owned API close; a borrowed facade stays caller-owned."""
        if self._managed_runtime_borrowed_api is not None:
            self._shutdown_state = "INCOMPLETE"
            return False, BtApiStoreError("managed runtime owns SDK API close")

        assembly = self._sdk_direct_api_assembly
        if assembly is None:
            if not self._sdk_owned_api:
                # No assembly is needed to prove that an API passed through
                # ``api=`` is borrowed.  The local Store shutdown is complete;
                # the caller remains responsible for this facade's lifetime.
                return True, None
            self._shutdown_state = "INCOMPLETE"
            return False, BtApiStoreError("store_sdk_api_ownership_unproven")
        try:
            assembly_api = assembly.api
            assembly_owns_api = assembly.owns_api
            assembly_close_api = assembly.close_api
        except Exception:
            self._shutdown_state = "INCOMPLETE"
            return False, BtApiStoreError("store_sdk_api_ownership_unproven")
        if (
            assembly_api is not api
            or type(assembly_owns_api) is not bool
            or assembly_owns_api is not self._sdk_owned_api
            or not callable(assembly_close_api)
        ):
            self._shutdown_state = "INCOMPLETE"
            return False, BtApiStoreError("store_sdk_api_ownership_mismatch")
        if not assembly_owns_api:
            # DirectApiAssembly.close_api() explicitly no-ops for borrowed
            # facades.  Keep the public Store health projection explicit that
            # PASS covers this Store's resources, not the caller's API close.
            return True, None

        def select_close():
            return assembly_close_api

        return self._get_sdk_close_controller().close(
            api,
            timeout,
            select_close=select_close,
            generation=lambda: self._command_runtime.generation,
        )

    def stop(self, timeout: Optional[float] = None):
        """Coordinate shutdown through the Backtrader lifecycle bridge."""
        owns_stop_slot = False
        transition_generation = None
        stop_deadline = None
        try:
            if self._sdk_mode or self._service_read_only:
                try:
                    stop_timeout = (
                        self._command_shutdown_timeout
                        if timeout is None
                        else max(float(timeout), 0.0)
                    )
                except (TypeError, ValueError, OverflowError):
                    raise BtApiStoreError("store_shutdown_timeout_invalid") from None
                if not math.isfinite(stop_timeout):
                    raise BtApiStoreError("store_shutdown_timeout_must_be_finite")
                stop_deadline = time.monotonic() + stop_timeout
                with self._sdk_start_state_lock:
                    if self._sdk_start_in_progress:
                        raise BtApiStoreError(
                            "store_sdk_start_already_in_progress"
                            if self._sdk_mode
                            else "store_service_start_already_in_progress"
                        )
                    if self._sdk_stop_in_progress:
                        raise BtApiStoreError(
                            "store_sdk_stop_already_in_progress"
                            if self._sdk_mode
                            else "store_service_stop_already_in_progress"
                        )
                    current_thread_id = threading.get_ident()
                    if self._sdk_api_activity_threads.get(current_thread_id, 0):
                        raise BtApiStoreError(
                            "store_sdk_stop_from_active_api_activity"
                            if self._sdk_mode
                            else "store_service_stop_from_active_api_activity"
                        )
                    if (
                        self._sdk_mode
                        and self._sdk_event_drain_owner_thread_id == current_thread_id
                    ):
                        raise BtApiStoreError("store_sdk_stop_from_event_drain")
                    # Take the stop slot before waiting so no new API activity
                    # or start can enter while the in-flight operation finishes.
                    if self._sdk_mode and self._sdk_event_batch_handoff and (
                        self._sdk_event_batch_stop_unproven()
                        or self._sdk_api_activity_count
                    ):
                        # Once stop races a claimed or in-flight claim, a later
                        # start cannot prove that the old producer is quiescent.
                        # Keep this fence sticky even if the bounded wait below
                        # times out or the claim completes while it is waiting.
                        self._sdk_event_batch_stop_requested = True
                    self._sdk_stop_in_progress = True
                    self._sdk_start_state_lock.notify_all()
                    owns_stop_slot = True
                    while (
                        (self._sdk_mode and self._sdk_event_drain_in_progress)
                        or self._sdk_api_activity_count
                    ):
                        remaining = stop_deadline - time.monotonic()
                        if remaining <= 0:
                            raise BtApiStoreError(
                                "store_sdk_event_drain_wait_timeout"
                                if self._sdk_mode
                                else "store_service_api_activity_wait_timeout"
                            )
                        # Condition.wait releases the shared state lock. API
                        # calls and provider I/O never run under this lock.
                        self._sdk_start_state_lock.wait(remaining)
                    if self._sdk_mode and self._sdk_event_batch_stop_unproven():
                        self._sdk_event_batch_stop_requested = True
                if self._sdk_mode:
                    # Refuse before lifecycle teardown if updates already
                    # handed to the Store have not reached the Broker.  The
                    # worker-stop barrier below repeats this check to cover
                    # completions published while the command worker drains.
                    try:
                        pending_updates = self._sdk_pending_broker_update_count()
                    except Exception:
                        self._sdk_stop_pending_broker_updates = True
                        self._shutdown_state = "INCOMPLETE"
                        self._command_health["stop_update_queue_unavailable"] += 1
                        raise BtApiStoreError(
                            "store_sdk_broker_update_queue_unavailable"
                        ) from None
                    if pending_updates:
                        self._sdk_stop_pending_broker_updates = True
                        self._shutdown_state = "INCOMPLETE"
                        self._command_health[
                            "stop_blocked_by_pending_broker_updates"
                        ] += 1
                        return self.get_command_health()
                    if self._sdk_event_batch_stop_unproven():
                        # A successful SDK close or an empty queue snapshot is
                        # not proof that deferred provider callbacks have
                        # stopped. Keep the route lease, API and notifier intact.
                        self._retain_unproven_sdk_event_batch()
                        return self.get_command_health()
            lifecycle_timeout = timeout
            if stop_deadline is not None:
                lifecycle_timeout = max(stop_deadline - time.monotonic(), 0.0)
            with self._calendar_status_lock:
                self._calendar_status_generation += 1
                transition_generation = self._calendar_status_generation
                self._calendar_status_transitions += 1
                self._calendar_status_stopping = True
            resync = getattr(self, "_tick_stream_resync", None)
            if resync is not None:
                resync.fence()  # no automatic tick-stream resync once stop began
            result = _stop_store(self, lifecycle_timeout, safe_log=_safe_log)
            shutdown_state = (
                result.get("shutdown_state")
                if isinstance(result, Mapping)
                else getattr(self, "_shutdown_state", None)
            )
            if shutdown_state == "PASS":
                self._sdk_stop_pending_broker_updates = False
                self._sdk_stop_command_worker_unproven = False
            with self._sdk_start_state_lock:
                failed_generation = self._sdk_partial_start_failed_generation
            if (
                failed_generation is not None
                and self._sdk_partial_start_stop_proven(result)
            ):
                with self._sdk_start_state_lock:
                    if self._sdk_partial_start_failed_generation == failed_generation:
                        self._sdk_partial_start_failed_generation = None
            return result
        finally:
            if owns_stop_slot:
                with self._sdk_start_state_lock:
                    self._sdk_stop_in_progress = False
                    self._sdk_start_state_lock.notify_all()
            if transition_generation is not None:
                with self._calendar_status_lock:
                    self._calendar_status_transitions -= 1

    def _sdk_partial_start_stop_proven(self, result: Any) -> bool:
        """Require concrete shutdown facts before clearing a partial-start fence."""
        shutdown_state = (
            result.get("shutdown_state")
            if isinstance(result, Mapping)
            else getattr(result, "shutdown_state", None)
        )
        if (
            shutdown_state != "PASS"
            or self._shutdown_state != "PASS"
            or self._started
            or self._connected
            or self._sdk_configured
            or self._market_stream_adapter.has_subscriptions
            or self._restart_blocked_by_close
            or self._sdk_close_thread is not None
            or self._sdk_api_close_state is not None
        ):
            return False
        if self._api is not None and not (
            self._managed_runtime_borrowed_api is self._api
            or self._last_successfully_closed_api is self._api
        ):
            return False
        try:
            command_state = self._command_runtime.snapshot()
            funding_health = self.get_funding_refresh_health()
        except Exception:
            return False
        return not (
            command_state.worker_alive
            or command_state.has_active_work
            or funding_health.get("worker_alive")
            or funding_health.get("inflight")
        )

    def _stop_synchronous_sdk(self, timeout: Optional[float] = None):
        """Coordinate synchronous SDK shutdown through the lifecycle bridge."""
        return _stop_synchronous_store_sdk(self, timeout)

    def getbroker(self, *args, **kwargs):
        """Return a BtApiBroker bound to this store."""
        explicit_binding = kwargs.pop("run_binding", None)
        if explicit_binding is not None:
            if self._run_binding is not None:
                verify_run_binding(self._run_binding, explicit_binding)
            elif not isinstance(explicit_binding, LiveRunBinding) or (
                self.live_mode is not None and explicit_binding.mode != self.live_mode
            ):
                raise LiveCompositionError("RUN_BINDING_MISMATCH")
        broker_cls = kwargs.pop("broker_cls", self.BrokerCls)
        if broker_cls is None:
            from ..brokers.btapibroker import BtApiBroker

            broker_cls = BtApiBroker

        broker = broker_cls(store=self, provider=self.provider, *args, **kwargs)
        if self._run_binding is not None:
            broker._run_binding = self._run_binding
        elif explicit_binding is not None:
            broker._run_binding = explicit_binding
        self._broker = broker
        return broker

    def getdata(self, *args, **kwargs):
        """Return a BtApiFeed bound to this store."""
        explicit_binding = kwargs.pop("run_binding", None)
        if explicit_binding is not None:
            if self._run_binding is not None:
                verify_run_binding(self._run_binding, explicit_binding)
            elif not isinstance(explicit_binding, LiveRunBinding) or (
                self.live_mode is not None and explicit_binding.mode != self.live_mode
            ):
                raise LiveCompositionError("RUN_BINDING_MISMATCH")
        data_cls = kwargs.pop("data_cls", self.DataCls)
        if data_cls is None:
            from ..feeds.btapifeed import BtApiFeed

            data_cls = BtApiFeed

        kwargs.setdefault("store", self)
        kwargs.setdefault("provider", self.provider)
        data = data_cls(*args, **kwargs)
        data._store = self
        if self._run_binding is not None:
            data._run_binding = self._run_binding
        elif explicit_binding is not None:
            data._run_binding = explicit_binding
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
        if self._gateway_mode:
            raise BtApiStoreError("GATEWAY_STRATEGY_BALANCE_UNAVAILABLE")
        if self._service_read_only:
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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

    def _sdk_position_query_timeout(self) -> float:
        """Per-route bound for one SDK position read (``account_position_query_timeout``).

        Defaults to 5 seconds. CTP's position query depends on the throttled
        instrument catalog (about one request per second) and needs longer.
        """
        value = {**self._config, **self._api_kwargs}.get("account_position_query_timeout", 5.0)
        if type(value) not in (int, float) or not 0 < value <= 120:
            raise BtApiStoreError("account_position_query_timeout must be in (0, 120] seconds")
        return float(value)

    def get_positions(
        self,
        force: bool = False,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return positions from the selected read path without fabricating freshness."""
        if self._gateway_mode:
            raise BtApiStoreError("GATEWAY_STRATEGY_POSITIONS_UNAVAILABLE")
        if self._service_read_only:
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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
        event = self._market_delivery_state.project_polled_event(
            symbol, channel, result, route, is_active, cleanup_unverified,
            previous_dropped, pump_only=pump_only,
            record_queue_state=self._record_market_stream_queue_state,
            record_drop=self._record_market_drop,
        )
        if result is None or channel != "tick" or pump_only:
            return event
        resync = self._tick_stream_resync
        if is_active:
            resync.observe_active(symbol)
            self._tick_stream_recovery.pop(symbol, None)
            return event
        # D62-38 point 7: remember why this channel delivers nothing, e.g. a
        # lost source still being replaced (PROVIDER_POLL_FAILED) or a restart
        # awaiting its resync; the Feed reads it through tick_stream_recovery_reason.
        self._tick_stream_recovery[symbol] = (
            "CLEANUP_UNVERIFIED"
            if cleanup_unverified
            else str(getattr(result, "recovery_code", None) or "RECOVERY_REQUIRED")
        )
        # RECOVERY_REQUIRED (CLEANUP_UNVERIFIED is never resynced). Only a
        # provider-declared restart is acknowledged here, with a backoff, and
        # never once this Store was asked to stop (continuity-7).
        if (
            not cleanup_unverified
            and resync.due(symbol, getattr(result, "recovery_code", None))
            and self._started
            and self._connected
        ):
            return self._resync_tick_stream(symbol, route)
        return event

    def tick_stream_recovery_reason(self, dataname: str) -> Optional[str]:
        """Why this Store's SDK tick channel for ``dataname`` delivers nothing, if so.

        Iteration 62, D62-38 point 7 (DELAYED during a disconnect or a
        recovery): the recovery code of the last polled result that was not
        ACTIVE -- ``PROVIDER_POLL_FAILED`` while a lost CTP source is replaced,
        ``PROVIDER_RESYNC_REQUIRED`` while a restart awaits its resync,
        ``CLEANUP_UNVERIFIED`` -- and ``None`` once the channel is ACTIVE again
        or was resynced. A disconnected source delivers no tick that could
        degrade the Feed, so the Feed reads this when a poll returns nothing.
        """
        return self._tick_stream_recovery.get(str(dataname))

    def _resync_tick_stream(self, symbol: str, route):
        """Acknowledge one provider-declared tick-stream restart (continuity-7).

        Iteration 62, D62-38 point 7: after a front disconnect the provider
        declares ``PROVIDER_RESYNC_REQUIRED`` once its new session ticks; the
        data loss of the lost session is acknowledged and the channel bound to
        the new session under a new epoch (the Feed treats it as a new scope
        and invalidates its open bar). A failed attempt (the provider is still
        recovering) keeps the stale/gap state and is retried after the backoff.
        """
        resync = self._tick_stream_resync
        attempt, warn_now = resync.begin_attempt(symbol)
        if warn_now:
            _safe_log(
                "warning",
                "btapistore: tick stream %s: provider market source restarted "
                "(PROVIDER_RESYNC_REQUIRED); acknowledging the data loss and resyncing",
                symbol,
            )
        try:
            result = self.accept_market_stream_resync(symbol, "tick", acknowledge_data_loss=True)
        except BtApiStoreError as exc:
            # The provider is still recovering (or the binding is unusable):
            # the stale/gap state stays; the restart stays open for a retry.
            self._market_delivery_state.increment(symbol, "tick_sdk_resync_failures")
            _safe_log(
                "debug",
                "btapistore: tick stream %s resync attempt %s failed (%s); retry_in=%.0fs",
                symbol,
                attempt,
                self._safe_exception_code(exc, "market_stream_resync_unavailable"),
                resync.retry_in(symbol),
            )
            return None
        attempts = resync.succeeded(symbol)
        self._tick_stream_recovery.pop(symbol, None)
        self._market_delivery_state.increment(symbol, "tick_sdk_resyncs")
        _safe_log(
            "info",
            "btapistore: tick stream %s resynced on a new epoch (attempts=%s)",
            symbol,
            attempts,
        )
        # A recovery event delivered with the resync is the new epoch's first
        # event; its queue state was recorded by accept_market_stream_resync.
        return self._market_delivery_state.project_polled_event(
            symbol,
            "tick",
            result,
            route,
            True,
            False,
            result.dropped_events,
            pump_only=False,
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
        if self._gateway_mode:
            raise BtApiStoreError("GATEWAY_MARKET_FEED_UNAVAILABLE")
        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError("store_sdk_lifecycle_transition_in_progress")
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
                return self._fetch_service_history(
                    dataname, timeframe, compression, since, limit
                )

        if compression is None:
            history_compression = 1
        elif type(compression) is int and compression > 0:
            history_compression = compression
        else:
            raise BtApiStoreError("history compression must be a positive integer")
        cache = self._history_cache
        hit, _key, _default_request, cached = cache.lookup(
            dataname, timeframe, history_compression, since, limit,
        )
        if hit:
            # A local cache hit does not use the SDK and remains readable after
            # Store stop, even when the borrowed API generation is retired.
            return cached

        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError(
                    "store_sdk_lifecycle_transition_in_progress"
                )
            # Keep the lease through SDK collection, Backtrader projection,
            # and cache publication so stop cannot close the API between a
            # successful fetch and its local history commit.
            return cache.fetch(
                dataname, timeframe, history_compression, since, limit,
                lambda default_request: self._fetch_sdk_history(
                    dataname, timeframe, history_compression, since, limit,
                    default_request,
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
                api = self._ensure_api_ready()
                orders = api.fetch_open_orders()
                if type(orders) is not list or any(
                    not isinstance(order, Mapping) for order in orders
                ):
                    raise BtApiStoreError(
                        "read-only service open-order snapshot is incomplete"
                    )
                self._open_orders_cache = [dict(order) for order in orders]
                self._last_open_orders_refresh = time.monotonic()
                return deepcopy(self._open_orders_cache)
        if self._sdk_mode:
            try:
                with self._sdk_api_activity() as admitted:
                    if not admitted:
                        raise BtApiStoreError(
                            "SDK open-order snapshot is incomplete or unverified"
                        )
                    snapshot = self.reconciliation_snapshot()
                    if snapshot.get("complete") is not True or snapshot.get("safe_to_resume") is not True:
                        raise BtApiStoreError("SDK open-order snapshot is incomplete or unverified")
                    orders = snapshot.get("open_orders")
                    if type(orders) is not list or any(not isinstance(item, Mapping) for item in orders):
                        raise BtApiStoreError("SDK open-order projection is incomplete")
                    self._open_orders_cache = [dict(order) for order in orders]
                    self._last_open_orders_refresh = time.monotonic()
                    return deepcopy(self._open_orders_cache)
            except BtApiStoreError:
                # Before the activity fence, a stopped borrowed facade reached
                # reconciliation_snapshot(), which projected this lifecycle
                # failure as an incomplete snapshot and the same public error.
                if self._sdk_borrowed_event_lifecycle_error() is not None:
                    raise BtApiStoreError(
                        "SDK open-order snapshot is incomplete or unverified"
                    ) from None
                raise
        raise BtApiStoreError("open-order reads require the unified SDK or read-only service facade")

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def getopenorders(self) -> List[Dict[str, Any]]:
        """Compatibility alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def _pop_live_bar_for_generation(self, dataname: str) -> Tuple[bool, Optional[Any]]:
        """Consume one bar atomically with respect to Store generation reset."""
        if not self._sdk_mode:
            return self._live_bar_queue.pop(dataname)
        with self._sdk_event_drain_lock:
            generation = self._stream_generation
            has_bar, bar, bar_generation = self._live_bar_queue.pop_entry(dataname)
        if (
            has_bar
            and bar_generation is not None
            and (
                bar_generation != generation
                or generation != self._stream_generation
            )
        ):
            self._record_market_drop(
                bar,
                "store_live_bar_generation_changed_during_poll",
                safety_impact="bar_not_delivered_across_store_generations",
                symbol=dataname,
                kind="bar",
            )
            self._mark_live_bar_queue_stale(
                dataname, "store_live_bar_generation_changed_during_poll"
            )
            return False, None
        return has_bar, bar

    def poll_live(self, dataname: str) -> Optional[Any]:
        """Poll a live bar, preserving source fields when explicitly requested."""
        if self._service_read_only:
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    return None
                api = self._ensure_api_ready()
                bar = api.poll_bar(dataname)
                return None if bar is None else self._copy_or_normalize_bar(bar)
        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    # Preserve the existing local-only handoff during the
                    # first Store start.  Start owns the transition slot (so
                    # stop cannot finish concurrently), and no earlier
                    # successful generation exists whose bars could be stale.
                    # No API readiness or event polling is allowed.
                    with self._sdk_start_state_lock:
                        start_in_progress = (
                            self._sdk_start_in_progress
                            and not self._sdk_stop_in_progress
                            and not self._has_successful_sdk_stream_generation
                        )
                    if not start_in_progress:
                        return None
                    has_queued_bar, bar = self._pop_live_bar_for_generation(dataname)
                    if not has_queued_bar:
                        return None
                    return cast(Optional[Dict[str, Any]], bar)
                # Admission and the local FIFO handoff form one Store activity:
                # stop cannot finish between the generation check and pop.
                with self._sdk_start_state_lock:
                    if (
                        self._has_successful_sdk_stream_generation
                        and not self._started
                    ):
                        borrowed_event_error = (
                            self._sdk_borrowed_event_lifecycle_error()
                        )
                        if borrowed_event_error is not None:
                            raise BtApiStoreError(borrowed_event_error)
                        return None
                has_queued_bar, bar = self._pop_live_bar_for_generation(dataname)
                if has_queued_bar:
                    return cast(Optional[Dict[str, Any]], bar)
                self._ensure_api_ready()
                self._drain_sdk_events()
                _has_queued_bar, bar = self._pop_live_bar_for_generation(dataname)
        else:
            has_queued_bar, bar = self._pop_live_bar_for_generation(dataname)
            if has_queued_bar:
                return cast(Optional[Dict[str, Any]], bar)
            self._ensure_api_ready()
            self._drain_sdk_events()
            _has_queued_bar, bar = self._pop_live_bar_for_generation(dataname)

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

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return None
                api = self._ensure_api_ready()
                tick = self._poll_sdk_market_stream(dataname, api)
                if tick is not None:
                    self._mark_feed_inflight(tick)
                if tick is not None:
                    self._latest_tick_cache.store(dataname, tick)
                return tick

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return None
            api = self._ensure_api_ready()
            if hasattr(api, "poll_tick"):
                tick = api.poll_tick(dataname)
            elif hasattr(api, "get_next_tick"):
                tick = api.get_next_tick(dataname)
            else:
                tick = None
            if tick is not None:
                self._latest_tick_cache.store(dataname, tick)
            return tick

    def get_latest_tick_snapshot(self, dataname: str):
        """Return the last consumed tick without issuing market-data I/O."""
        from bt_api_py.instrument_metadata_aliases import find_alias_match

        return self._latest_tick_cache.snapshot(
            dataname,
            find_alias_match=find_alias_match,
        )

    def poll_orderbook(self, dataname: str, *, depth: Optional[int] = None):
        """Poll a single live orderbook snapshot from the API."""
        if not self._connected:
            return None

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return None
                api = self._ensure_api_ready()
                book = self._poll_sdk_market_stream(
                    dataname,
                    api,
                    channel="orderbook",
                    depth=depth,
                )
                if book is not None:
                    self._mark_feed_inflight(book)
                return book

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return None
            api = self._ensure_api_ready()
            if hasattr(api, "poll_orderbook"):
                return api.poll_orderbook(dataname)
            if hasattr(api, "get_next_orderbook"):
                return api.get_next_orderbook(dataname)
            return None

    def has_pending_tick(self, dataname: str) -> bool:
        """Return whether the API has queued live ticks for a symbol."""
        if not self._connected:
            return False

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return False
                api = self._ensure_api_ready()
                self._poll_sdk_market_stream(dataname, api, pump_only=True)
                if not self._market_stream_adapter.has_binding(str(dataname), "tick"):
                    return False
                depth = self._sdk_market_stream_queue_depth(dataname, "tick")
                self._market_delivery_state.set_state(str(dataname), "tick_queue_depth", depth)
                return depth > 0

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return False
            api = self._ensure_api_ready()
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
        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return False
            api = self._ensure_api_ready()
            method = getattr(api, "is_source_exhausted", None)
            return bool(method(dataname)) if callable(method) else False

    def get_source_event_time_watermark(self, dataname: str):
        """Return a finite source's final event-time watermark, if declared."""

        if not self._connected:
            return None
        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return None
            api = self._ensure_api_ready()
            method = getattr(api, "get_source_event_time_watermark", None)
            return method(dataname) if callable(method) else None

    def has_pending_orderbook(self, dataname: str) -> bool:
        """Return whether the API has queued live orderbooks for a symbol."""
        if not self._connected:
            return False

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return False
                api = self._ensure_api_ready()
                self._poll_sdk_market_stream(
                    dataname, api, channel="orderbook", pump_only=True
                )
                if not self._market_stream_adapter.has_binding(dataname, "orderbook"):
                    return False
                return self._sdk_market_stream_queue_depth(dataname, "orderbook") > 0

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return False
            api = self._ensure_api_ready()
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

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return False
                api = self._ensure_api_ready()
                return self._market_stream_adapter.supports_channel(
                    str(dataname), api, channel="tick", depth=None
                )

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return False
            api = self._ensure_api_ready()
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

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return False
                api = self._ensure_api_ready()
                return self._market_stream_adapter.supports_channel(
                    str(dataname), api, channel="orderbook", depth=None
                )

        with self._sdk_api_activity() as admitted:
            if not admitted or not self._connected:
                return False
            api = self._ensure_api_ready()
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
        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError("store_sdk_lifecycle_transition_in_progress")
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

    def _sdk_borrowed_event_lifecycle_error(self) -> Optional[str]:
        """Return why a stopped borrowed SDK event source cannot be reused.

        The SDK owns its poll FIFO.  A successful Store generation cannot
        prove that a caller-owned facade's next batch belongs to a later Store
        generation, so stop retires that Store/facade pairing until the caller
        constructs a fresh Store around a fresh facade.  Managed-runtime
        facades already have a stronger one-session contract; surface that
        existing reason before any event poll as well.
        """
        if not self._sdk_mode or self._service_read_only or self._sdk_owned_api:
            return None
        if self._managed_runtime_borrowed_api is not None:
            if self._managed_runtime_stopped:
                return "managed_runtime_store_session_already_stopped"
            return None
        if self._sdk_borrowed_event_source_retired or (
            self._has_successful_sdk_stream_generation and not self._started
        ):
            return "store_borrowed_sdk_api_restart_requires_fresh_facade"
        return None

    def _begin_sdk_api_activity(self) -> bool:
        """Admit one Store operation that may touch the SDK facade."""
        if not self._sdk_mode and not self._service_read_only:
            return True
        thread_id = threading.get_ident()
        with self._sdk_start_state_lock:
            depth = self._sdk_api_activity_threads.get(thread_id, 0)
            if depth == 0:
                if self._sdk_stop_in_progress:
                    return False
                if (
                    self._sdk_start_in_progress
                    and self._sdk_start_owner_thread_id != thread_id
                ):
                    return False
                borrowed_event_error = self._sdk_borrowed_event_lifecycle_error()
                if borrowed_event_error is not None:
                    raise BtApiStoreError(borrowed_event_error)
            self._sdk_api_activity_threads[thread_id] = depth + 1
            self._sdk_api_activity_count += 1
        return True

    def _finish_sdk_api_activity(self) -> None:
        """Release one SDK operation lease and wake bounded stop waiters."""
        thread_id = threading.get_ident()
        with self._sdk_start_state_lock:
            depth = self._sdk_api_activity_threads.get(thread_id, 0)
            if depth <= 0 or self._sdk_api_activity_count <= 0:
                raise BtApiStoreError("store_sdk_api_activity_lease_owner_mismatch")
            if depth == 1:
                del self._sdk_api_activity_threads[thread_id]
            else:
                self._sdk_api_activity_threads[thread_id] = depth - 1
            self._sdk_api_activity_count -= 1
            self._sdk_start_state_lock.notify_all()

    @contextmanager
    def _sdk_api_activity(self):
        """Coordinate one complete facade operation with Store stop."""
        admitted = self._begin_sdk_api_activity()
        if not admitted:
            yield False
            return
        try:
            yield True
        finally:
            if self._sdk_mode or self._service_read_only:
                self._finish_sdk_api_activity()

    @contextmanager
    def _sdk_pending_broker_update_activity(self):
        """Lease only the Store-local inbox while a managed facade is retired.

        A managed runtime may still own a late completion after Store stop has
        fenced SDK access.  Draining that already-published local item is safe,
        but it must remain coordinated with a concurrent stop and must never
        run readiness or poll the borrowed facade again.
        """
        admitted = False
        thread_id = threading.get_ident()
        with self._sdk_start_state_lock:
            depth = self._sdk_api_activity_threads.get(thread_id, 0)
            if (
                self._sdk_mode
                and self._managed_runtime_borrowed_api is not None
                and (
                    self._sdk_stop_pending_broker_updates
                    or self._sdk_stop_command_worker_unproven
                )
                and not self._sdk_stop_in_progress
                and not self._sdk_start_in_progress
            ):
                self._sdk_api_activity_threads[thread_id] = depth + 1
                self._sdk_api_activity_count += 1
                admitted = True
        try:
            yield admitted
        finally:
            if admitted:
                self._finish_sdk_api_activity()

    def poll_broker_update(self):
        """Poll a normalized broker-side order/trade/error update from the API."""
        if (
            self._sdk_mode
            and self._managed_runtime_borrowed_api is not None
            and (
                self._sdk_stop_pending_broker_updates
                or self._sdk_stop_command_worker_unproven
            )
        ):
            # A stopped managed-runtime facade is no longer a Store API
            # resource.  Only consume updates already handed to this Store;
            # in particular do not re-enter readiness, an outbox reader, or
            # SDK poll_events while completing the retained handoff.
            with self._sdk_pending_broker_update_activity() as admitted:
                if not admitted:
                    return None
                update = self._command_runtime.pop_update()
                if update is None:
                    return None
                update = self.redact_runtime_value(update)
                self._emit_broker_runtime_event(update)
                return update

        if not self._connected:
            if self._sdk_mode and self._sdk_stop_pending_broker_updates:
                # A stop refused teardown because the Broker inbox was not
                # handed off.  Even when the API is disconnected, allow the
                # caller to consume that retained local update without
                # reconnecting or polling the SDK.
                with self._sdk_api_activity() as admitted:
                    if not admitted:
                        return None
                    update = self._command_runtime.pop_update()
                    if update is None:
                        return None
                    update = self.redact_runtime_value(update)
                    self._emit_broker_runtime_event(update)
                    return update
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

        if self._sdk_mode:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return None
                self._ensure_api_ready()
                self._drain_sdk_events()
                update = self._command_runtime.pop_update()
                if update is None:
                    return None
                update = self.redact_runtime_value(update)
                self._emit_broker_runtime_event(update)
                return update
        else:
            with self._sdk_api_activity() as admitted:
                if not admitted or not self._connected:
                    return None
                api = self._ensure_api_ready()
                if hasattr(api, "poll_broker_update"):
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

    def _sdk_pending_broker_update_count(self) -> int:
        """Return the exact queued Broker-update count or fail closed."""
        snapshot = self._command_runtime.snapshot()
        count = getattr(snapshot, "completion_depth", None)
        if type(count) is not int or count < 0:
            raise BtApiStoreError("store_sdk_broker_update_queue_unproven")
        return count

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

    #: Lease-granting fence from ``bind_account_owner_fence``; ``None`` = unfenced.
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
        # Install the listener before the first read: pushes during a verified
        # cut's snapshot read are buffered and replayed by the SDK bootstrap.
        self._account_position_subscription = subscription
        subscription.start()
        return subscription

    def position_stream_cut_capability(self, account_ref):
        """``(capability, reason)``: the provider's declared query/push cut, if any.

        Resolution and the per-provider missing facts belong to the SDK
        (``bt_api_py.position_stream_bootstrap.resolve_position_stream_cut``).
        """

        try:
            from bt_api_py.position_stream_bootstrap import resolve_position_stream_cut
        except ImportError:
            return None, "SDK_CUT_CONTRACT_UNAVAILABLE"
        return resolve_position_stream_cut(self._api, self.provider)

    def bind_account_owner_fence(self, fence):
        """Install the Broker's account-owner fence for queued SDK writes.

        ``fence()`` is an early pre-check; the command worker's last
        pre-dispatch step takes ``fence.acquire_dispatch_lease(...)`` (an SDK
        ``DispatchLease``) and holds it for the whole provider call, so a
        handoff QUIESCE either refuses it or waits for it / records it
        UNKNOWN (iteration 60, G1). Host-local only; cross-host exclusivity
        needs provider-side session revocation. A fence cannot be replaced.
        """

        if self._account_owner_fence is not None:
            raise ValueError("this store is already bound to an account-owner fence")
        if not callable(fence) or not callable(getattr(fence, "acquire_dispatch_lease", None)):
            raise ValueError("an account-owner fence that grants dispatch leases is required")
        self._account_owner_fence = fence

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
        # Preserve the dynamic getter probe; order.info may expose it via descriptor.
        _ = getattr(order_info, "get", lambda *_args: None)
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
        assembly = self._sdk_direct_api_assembly
        if self._managed_runtime_borrowed_api is not None:
            if self._api is self._managed_runtime_borrowed_api:
                api_ownership = "MANAGED_RUNTIME_BORROWED"
                api_close_state = "NOT_CLOSED_BY_STORE"
            else:
                api_ownership = "UNPROVEN"
                api_close_state = "OWNERSHIP_MISMATCH"
        elif assembly is not None:
            try:
                assembly_api = assembly.api
                assembly_owns_api = assembly.owns_api
                closed_owned_assembly = (
                    self._api is None
                    and self._sdk_owned_api
                    and assembly_api is self._last_successfully_closed_api
                    and type(assembly_owns_api) is bool
                    and assembly_owns_api is self._sdk_owned_api
                )
                assembly_matches = (
                    type(assembly_owns_api) is bool
                    and assembly_owns_api is self._sdk_owned_api
                    and (assembly_api is self._api or closed_owned_assembly)
                )
            except Exception:
                closed_owned_assembly = False
                assembly_matches = False
            if not assembly_matches:
                api_ownership = "UNPROVEN"
                api_close_state = "OWNERSHIP_MISMATCH"
            elif closed_owned_assembly:
                api_ownership = "STORE_OWNED"
                api_close_state = "CLOSED_BY_STORE"
            elif self._sdk_owned_api:
                api_ownership = "STORE_OWNED"
                if self._api is not None:
                    api_close_state = (
                        "CLOSE_OUTCOME_UNCERTAIN"
                        if self._sdk_api_close_state is not None
                        else "API_BOUND"
                    )
                elif self._last_successfully_closed_api is not None:
                    api_close_state = "CLOSED_BY_STORE"
                else:
                    api_close_state = "API_NOT_CREATED"
            else:
                api_ownership = "CALLER_BORROWED"
                api_close_state = "NOT_CLOSED_BY_STORE"
        elif not self._sdk_owned_api:
            api_ownership = "CALLER_BORROWED"
            api_close_state = "NOT_CLOSED_BY_STORE"
        elif self._api is None:
            api_ownership = "STORE_OWNED"
            api_close_state = "CLOSED_BY_STORE" if self._last_successfully_closed_api is not None else "API_NOT_CREATED"
        else:
            api_ownership = "UNPROVEN"
            api_close_state = "OWNERSHIP_UNPROVEN"
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
            "shutdown_blocked_by_broker_update_handoff": bool(
                self._sdk_stop_pending_broker_updates
            ),
            "shutdown_blocked_by_event_batch_producer_quiescence": bool(
                self._sdk_event_batch_stop_unproven()
            ),
            "shutdown_blocked_by_command_worker": bool(
                self._sdk_stop_command_worker_unproven
            ),
            "sdk_api_ownership": api_ownership,
            "sdk_api_close_state": api_close_state,
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
            return self._contract_metadata_cache.snapshot_all()

        from bt_api_py.instrument_metadata_aliases import find_alias_match

        aliases = _contract_metadata_aliases(dataname)
        metadata = self.contract_metadata
        alias_fn = _contract_metadata_aliases
        found, value = self._contract_metadata_cache.lookup(
            dataname,
            metadata=metadata,
            aliases=aliases,
            alias_fn=alias_fn,
            find_alias_match=find_alias_match,
        )
        if found:
            return value

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
        self._contract_metadata_cache.store_normalized(dataname, metadata)
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

    def _install_package_calendar_seed(self, config_file):
        """Materialize the committed in-package seed and return its store root.

        D67-01: ``root: package_seed`` is an explicit selection of the
        synthetic in-package calendar, not a daily-updated directory.  The
        runtime needs a readable published CURRENT, so the seed is installed
        into a deterministic Store runtime directory beside the explicit
        configuration file (``calendar_package_seed``) using the committed SDK
        loader/installer.  Installation is single-writer, reports UNKNOWN
        separately and never replaces a different CURRENT; any failure is a
        finite Store refusal, never a silently empty calendar.
        """
        from pathlib import Path

        try:
            config_path = Path(config_file)
            if not config_path.is_absolute() or not config_path.name:
                raise ValueError("calendar config file is not absolute")
            root = config_path.parent / "calendar_package_seed"
            root.mkdir(mode=0o700, exist_ok=True)
        except Exception:
            raise BtApiStoreError("calendar_package_seed_install_failed") from None
        try:
            from bt_api_py.trading_calendar_package_seed import (
                INSTALL_INSTALLED,
                INSTALL_NOT_COMMITTED,
                INSTALL_UNCHANGED,
                INSTALL_UNKNOWN,
                install_package_seed,
            )
            from bt_api_py.trading_calendar_store import TradingCalendarStore

            result = install_package_seed(str(root))
            if (
                result.status == INSTALL_NOT_COMMITTED
                and result.reason == "STORE_NOT_INITIALIZED"
            ):
                # The installer refuses to invent store policy; initialize the
                # explicit auto policy first, then retry exactly once.
                TradingCalendarStore(root).initialize_review_policy(
                    config_read_succeeded=True
                )
                result = install_package_seed(str(root))
        except BtApiStoreError:
            raise
        except Exception:
            raise BtApiStoreError("calendar_package_seed_install_failed") from None
        if result.status == INSTALL_UNKNOWN:
            raise BtApiStoreError("calendar_package_seed_unknown")
        if result.status not in (INSTALL_INSTALLED, INSTALL_UNCHANGED):
            raise BtApiStoreError("calendar_package_seed_install_failed")
        return root

    def _configure_owned_facade_calendar(self, api):
        """Mirror explicit calendar routes into a Store-owned facade once.

        A borrowed facade, or one returned by a caller factory, can be shared
        with other Stores whose calendar directories differ; rewriting it
        would break their isolation, so it is never touched.  Only a facade
        this Store created itself is configured, and only after the Store
        proved the route roots.
        """
        with self._calendar_status_lock:
            roots = self._calendar_facade_route_roots
            if not roots or self._calendar_facade_attempted_api is api:
                return
            if not self._sdk_owned_api or self._sdk_custom_api_factory:
                return
            self._calendar_facade_attempted_api = api
            self._calendar_facade_configuration = "CONFIGURING"
        try:
            configure = getattr(api, "configure_trading_calendar_status", None)
            if not callable(configure):
                raise ValueError("facade calendar configuration is unavailable")
            configure(route_roots=dict(roots))
        except Exception:
            with self._calendar_status_lock:
                self._calendar_facade_configuration = "FAILED"
            _safe_log("warning", "btapistore:calendar_facade_configuration_failed")
            return
        with self._calendar_status_lock:
            self._calendar_facade_configuration = "CONFIGURED"

    def trading_calendar_status(self, exchange_name: Optional[str] = None):
        """Observe local SDK calendar status for exact configured routes.

        Return ``{status, reason, routes}`` for both single and multiple routes;
        each successful value in ``routes`` is the unchanged SDK observation.
        The aggregate is ``OBSERVED`` if every route observed CURRENT,
        ``PARTIAL`` if only some did, and ``UNKNOWN`` if none did.
        Store-side failures have ``status`` and ``reason`` attributes. No route
        argument selects every configured route; an explicit argument must be
        an exact configured key. With local configuration, ``sources`` maps
        routes to ``LOCAL_CONFIG`` or ``SDK_FACADE``. Local observations are
        unauthenticated and not bound to strategy use or trading authorization.
        """
        with self._calendar_status_lock:
            configured_routes = tuple(self._sdk_exchanges)
            generation = self._calendar_status_generation
            stream_generation = self._stream_generation
            api = self._api
            local_reader = self._calendar_local_reader
            local_routes = self._calendar_local_routes
            package_seed_routes = self._calendar_package_seed_routes
            ready = (
                self._sdk_mode and not self._gateway_mode and not self._service_read_only
                and self._started and self._connected and self._sdk_configured
                and api is not None and not self._calendar_status_transitions
                and not self._calendar_status_stopping
            )

        routes = tuple(
            route for route in configured_routes
            if type(route) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", route)
        )
        invalid_routes = len(routes) != len(configured_routes)
        if exchange_name is not None:
            if type(exchange_name) is not str or exchange_name not in routes:
                return {"status": "UNKNOWN", "reason": "ROUTE_UNCONFIGURED", "routes": {}}
            routes = (exchange_name,)
            invalid_routes = False
        if not routes:
            return {"status": "UNKNOWN",
                    "reason": "INVALID_CONFIGURED_ROUTE" if invalid_routes else "ROUTE_UNAVAILABLE",
                    "routes": {}}

        def unavailable(reason):
            return {route: _CalendarStatusUnavailable(reason=reason) for route in routes}

        def valid_live_routes(value):
            return (type(value) is list and all(
                type(route) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", route)
                for route in value
            )
                    and len(set(value)) == len(value))

        if not ready:
            return {"status": "UNKNOWN", "reason": "STORE_UNAVAILABLE",
                    "routes": unavailable("STORE_UNAVAILABLE")}
        try:
            from bt_api_py.trading_calendar_runtime_status import TradingCalendarStatus

            list_routes = getattr(api, "list_exchanges", None)
            if local_reader is not None and all(route in local_routes for route in routes):
                reader = None
            else:
                try:
                    reader = getattr(api, "trading_calendar_status", None)
                except Exception:
                    if local_reader is None:
                        raise
                    reader = None
            if not callable(list_routes) or (local_reader is None and not callable(reader)):
                return {"status": "UNKNOWN", "reason": "CAPABILITY_UNAVAILABLE",
                        "routes": unavailable("CAPABILITY_UNAVAILABLE")}
            live_routes = list_routes()
            if not valid_live_routes(live_routes):
                raise ValueError("invalid route projection")
        except Exception:
            return {"status": "UNKNOWN", "reason": "ROUTE_UNAVAILABLE",
                    "routes": unavailable("ROUTE_UNAVAILABLE")}

        observations = {}
        sources = {}
        observed_count = 0
        for route in routes:
            is_local = local_reader is not None and route in local_routes
            if local_reader is not None:
                sources[route] = (
                    "LOCAL_CONFIG_PACKAGE_SEED"
                    if route in package_seed_routes
                    else "LOCAL_CONFIG" if is_local else "SDK_FACADE"
                )
            if route not in live_routes:
                observations[route] = _CalendarStatusUnavailable(reason="ROUTE_UNAVAILABLE")
                continue
            try:
                selected_reader = local_reader.status if is_local else reader
                if not callable(selected_reader):
                    observations[route] = _CalendarStatusUnavailable(reason="CAPABILITY_UNAVAILABLE")
                    continue
                value = selected_reader(route)
                if not _safe_calendar_observation(value, TradingCalendarStatus):
                    raise ValueError("invalid status")
                observations[route] = value
                if value.status == "OBSERVED_UNAUTHENTICATED":
                    observed_count += 1
            except Exception:
                observations[route] = _CalendarStatusUnavailable(reason="READ_UNAVAILABLE")

        try:
            list_routes_after = getattr(api, "list_exchanges", None)
            if not callable(list_routes_after):
                raise ValueError("route projection unavailable")
            live_routes_after = list_routes_after()
            if (not valid_live_routes(live_routes_after)
                    or set(live_routes_after) != set(live_routes)):
                raise ValueError("route projection changed")
        except Exception:
            return {"status": "UNKNOWN", "reason": "ROUTE_SET_CHANGED",
                    "routes": unavailable("ROUTE_SET_CHANGED")}

        with self._calendar_status_lock:
            current = (
                generation == self._calendar_status_generation
                and stream_generation == self._stream_generation and self._api is api
                and tuple(self._sdk_exchanges) == configured_routes
                and self._started and self._connected and self._sdk_configured
                and not self._calendar_status_transitions and not self._calendar_status_stopping
            )
            if not current:
                return {"status": "UNKNOWN", "reason": "STORE_CHANGED",
                        "routes": unavailable("STORE_CHANGED")}
            if not observed_count:
                status = "UNKNOWN"
            elif invalid_routes or observed_count != len(routes):
                status = "PARTIAL"
            else:
                status = "OBSERVED"
            result = {"status": status,
                    "reason": ("INVALID_CONFIGURED_ROUTE" if invalid_routes else
                               "ROUTE_RESULTS" if status == "OBSERVED" else
                               "PARTIAL_ROUTE_RESULTS" if status == "PARTIAL" else
                               "ROUTES_UNAVAILABLE"),
                    "routes": observations}
            if local_reader is not None:
                result["sources"] = sources
            return result

    def trading_calendar_query(self, route, *, venue, kind, product, contract, trading_day,
                               mode=None):
        """Read a CTP-format simulation calendar for one explicit configured route.

        Route selects a local root or SDK facade route; it does not authenticate
        provider identity. Results do not bind a strategy or authorize account use.
        """
        def unavailable(reason):
            return _CalendarStatusUnavailable(reason=reason)

        if type(mode) is not str or mode != "SIMULATION_ONLY":
            return unavailable("SIMULATION_MODE_REQUIRED")
        route_pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        if (type(route) is not str or re.fullmatch(route_pattern, route) is None
                or any(type(value) is not str or re.fullmatch(route_pattern, value) is None
                       for value in (venue, kind, product, contract))
                or type(trading_day) is not _dt.date):
            return unavailable("INVALID_QUERY_SCOPE")
        if self._gateway_mode:
            return self._gateway_trading_calendar_query(
                route, venue=venue, kind=kind, product=product, contract=contract,
                trading_day=trading_day,
            )
        with self._calendar_status_lock:
            configured_routes = tuple(self._sdk_exchanges)
            generation = self._calendar_status_generation
            stream_generation = self._stream_generation
            api = self._api
            local_reader = self._calendar_local_reader
            local_routes = self._calendar_local_routes
            ready = (
                self._sdk_mode and not self._gateway_mode and not self._service_read_only
                and self._started and self._connected and self._sdk_configured
                and api is not None and not self._calendar_status_transitions
                and not self._calendar_status_stopping
            )
        if route not in configured_routes:
            return unavailable("ROUTE_UNCONFIGURED")
        if not ready:
            return unavailable("STORE_UNAVAILABLE")

        def valid_live_routes(value):
            return (type(value) is list and all(
                type(item) is str and re.fullmatch(route_pattern, item) is not None
                for item in value
            ) and len(set(value)) == len(value))

        try:
            from bt_api_py.trading_calendar_runtime_status import (
                TradingCalendarCurrentQuery, TradingCalendarQueryWindow, TradingCalendarStatusReader,
            )
            from bt_api_py.bt_api import BtApi
            from zoneinfo import ZoneInfo

            list_routes = getattr(api, "list_exchanges", None)
            is_local = local_reader is not None and route in local_routes
            reader = (getattr(local_reader, "query", None)
                      if is_local
                      else getattr(api, "trading_calendar_query", None))
            if ((is_local and type(local_reader) is not TradingCalendarStatusReader)
                    or (not is_local and not isinstance(api, BtApi))):
                return unavailable("CAPABILITY_UNAVAILABLE")
            token_owner = local_reader if is_local else api
            token_method = getattr(token_owner, "configuration_token" if is_local else
                                   "trading_calendar_configuration_token", None)
            token_check = getattr(token_owner, "configuration_is_current" if is_local else
                                  "trading_calendar_configuration_is_current", None)
            if not callable(token_method) or not callable(token_check):
                return unavailable("CAPABILITY_UNAVAILABLE")
            try:
                reader_token = token_method()
            except Exception:
                return unavailable("CAPABILITY_UNAVAILABLE")
            if reader_token is None:
                return unavailable("CAPABILITY_UNAVAILABLE")
            if not callable(list_routes) or not callable(reader):
                return unavailable("CAPABILITY_UNAVAILABLE")
            live_routes = list_routes()
            if not valid_live_routes(live_routes):
                return unavailable("ROUTE_UNAVAILABLE")
        except Exception:
            return unavailable("ROUTE_UNAVAILABLE")

        value = unavailable("ROUTE_UNAVAILABLE")
        if route in live_routes:
            try:
                result = reader(route, venue=venue, kind=kind, product=product,
                                contract=contract, trading_day=trading_day, mode=mode)
                enums = {
                    "source_authentication": "NOT_PROVEN", "identity_authentication": "NOT_PROVEN",
                    "publication_authentication": "NOT_PROVEN", "route_mapping": "CALLER_DECLARED_ONLY",
                    "bound": "NOT_BOUND", "observation": "CURRENT_NOT_PINNED",
                    "trading_day_transition": "NOT_PROVEN", "environment": "SIMULATION_ONLY",
                    "account_use": "NOT_AUTHORIZED", "provider": "CTP",
                    "provider_selection": "EXPLICIT_CTP_ONLY_ROUTE_UNVERIFIED",
                }
                if (type(result) is not TradingCalendarCurrentQuery
                        or any(type(getattr(result, key)) is not str for key in
                               ("status", "reason", "coverage_status", "source_classification"))
                        or any(type(getattr(result, key)) is not str or getattr(result, key) != expected
                               for key, expected in enums.items())
                        or type(result.windows) is not tuple or len(result.windows) > 10000
                        or type(result.source_ids) is not tuple or len(result.source_ids) > 1000
                        or any(type(item) is not str or re.fullmatch(route_pattern, item) is None
                               for item in result.source_ids)
                        or len(set(result.source_ids)) != len(result.source_ids)):
                    raise ValueError("invalid query result")
                if result.status == "UNKNOWN":
                    if (result.reason not in {"SIMULATION_MODE_REQUIRED", "INVALID_ROUTE",
                            "INVALID_QUERY_SCOPE", "ROUTE_UNCONFIGURED", "CURRENT_UNAVAILABLE",
                            "PROVIDER_UNAVAILABLE", "COVERAGE_UNAVAILABLE", "CALENDAR_UNAVAILABLE",
                            "SCOPE_OR_DATA_UNAVAILABLE", "CONFIGURATION_CHANGED"}
                            or result.windows or result.source_ids
                            or result.source_classification != "UNVERIFIED"
                            or result.coverage_status != "UNKNOWN"
                            or getattr(result, "data_origin", "UNSPECIFIED") != "UNSPECIFIED"
                            or getattr(result, "simulation_provenance", None) is not None
                            or any(item is not None for item in (result.calendar_ref,
                                   result.publication_id, result.content_sha256, result.version_sha256))):
                        raise ValueError("invalid unknown query result")
                elif result.status == "COMPLETE":
                    origin = getattr(result, "data_origin", "UNSPECIFIED")
                    provenance = getattr(result, "simulation_provenance", None)
                    if type(origin) is not str or origin not in {
                        "UNSPECIFIED", "AKSHARE_MOCK", "SYNTHETIC_MOCK"
                    }:
                        raise ValueError("invalid query origin")
                    if ("AKSHARE.simulation_unverified" in result.source_ids
                            and (origin != "AKSHARE_MOCK" or provenance is None)):
                        raise ValueError("missing mixed query provenance")
                    if provenance is not None:
                        expected_classification = "AKSHARE_MOCK"
                        if origin != "AKSHARE_MOCK":
                            raise ValueError("invalid mixed query origin")
                    elif origin == "AKSHARE_MOCK":
                        expected_classification = (
                            "DECLARED_MOCK" if set(result.source_ids) == {"MOCK.simulation_only"}
                            else "UNVERIFIED")
                    else:
                        expected_classification = (
                            "DECLARED_MOCK" if "MOCK.simulation_only" in result.source_ids
                            else "UNVERIFIED")
                    if (result.reason != "EXPLICIT_DATA" or result.coverage_status != "DECLARED_UNVERIFIED"
                            or result.source_classification != expected_classification
                            or not result.source_ids
                            or any(type(item) is not str or re.fullmatch(
                                r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", item) is None
                                for item in (result.calendar_ref, result.publication_id))
                            or any(type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None
                                   for item in (result.content_sha256, result.version_sha256))):
                        raise ValueError("invalid complete query result")
                    previous_end = None
                    for window in result.windows:
                        if (type(window) is not TradingCalendarQueryWindow
                                or type(window.window_id) is not str
                                or re.fullmatch(route_pattern, window.window_id) is None
                                or type(window.phase) is not str or window.phase not in {"continuous", "auction"}
                                or type(window.trading_day) is not _dt.date or window.trading_day != trading_day
                                or type(window.interval_semantics) is not str
                                or window.interval_semantics != "START_INCLUSIVE_END_EXCLUSIVE"
                                or any(type(item) is not _dt.datetime for item in
                                       (window.start_utc, window.end_utc, window.start_local, window.end_local))
                                or window.start_utc.tzinfo is not _UTC or window.end_utc.tzinfo is not _UTC
                                or type(window.start_local.tzinfo) is not ZoneInfo
                                or type(window.end_local.tzinfo) is not ZoneInfo
                                or window.start_local.tzinfo.key != "Asia/Shanghai"
                                or window.end_local.tzinfo.key != "Asia/Shanghai"
                                or window.start_local.astimezone(_UTC) != window.start_utc
                                or window.end_local.astimezone(_UTC) != window.end_utc
                                or window.start_utc >= window.end_utc
                                or (previous_end is not None and window.start_utc < previous_end)):
                            raise ValueError("invalid query window")
                        previous_end = window.end_utc
                    if provenance is not None and not _safe_calendar_mixed_provenance(
                            result, venue, kind, product, contract, trading_day):
                        raise ValueError("invalid mixed query provenance")
                else:
                    raise ValueError("invalid query status")
                value = result
            except Exception:
                value = unavailable("READ_UNAVAILABLE")

        try:
            list_routes_after = getattr(api, "list_exchanges", None)
            live_routes_after = list_routes_after() if callable(list_routes_after) else None
            if not valid_live_routes(live_routes_after) or set(live_routes_after) != set(live_routes):
                return unavailable("ROUTE_SET_CHANGED")
        except Exception:
            return unavailable("ROUTE_SET_CHANGED")
        try:
            token_current = token_check(reader_token)
        except Exception:
            return unavailable("CAPABILITY_UNAVAILABLE")
        if token_current is False:
            return unavailable("CONFIGURATION_CHANGED")
        if token_current is not True:
            return unavailable("CAPABILITY_UNAVAILABLE")
        with self._calendar_status_lock:
            if not (generation == self._calendar_status_generation
                    and stream_generation == self._stream_generation and self._api is api
                    and tuple(self._sdk_exchanges) == configured_routes
                    and self._calendar_local_reader is local_reader
                    and self._calendar_local_routes == local_routes
                    and self._sdk_mode and not self._gateway_mode and not self._service_read_only
                    and self._started and self._connected and self._sdk_configured
                    and not self._calendar_status_transitions and not self._calendar_status_stopping):
                return unavailable("STORE_CHANGED")
            return value

    def _gateway_trading_calendar_query(self, route, *, venue, kind, product, contract,
                                        trading_day):
        """Read one SDK-owned Gateway observation; never open local CURRENT."""
        def unavailable(reason):
            return _CalendarStatusUnavailable(reason=reason)

        with self._calendar_status_lock:
            api = self._api
            config = self._gateway_strategy_config
            run_lock = self._gateway_run_lock
            generation = self._gateway_session_generation
            status_generation = self._calendar_status_generation
            stream_generation = self._stream_generation
            routes = tuple(self._sdk_exchanges)
            ready = (self._gateway_mode and not self._service_read_only and self._started
                     and self._connected and not self._gateway_closed
                     and self._gateway_pid == os.getpid() and api is not None
                     and run_lock is not None and run_lock.held
                     and not self._calendar_status_transitions and not self._calendar_status_stopping)
        if route not in routes:
            return unavailable("ROUTE_UNCONFIGURED")
        if not ready:
            return unavailable("STORE_UNAVAILABLE")
        try:
            from bt_api_py.gateway_api import GatewayBtApi
            from bt_api_py.gateway_strategy_calendar import GatewayCalendarQueryResult

            settings = None if config is None else config.calendar_settings
            if type(api) is not GatewayBtApi or settings is None:
                return unavailable("CAPABILITY_UNAVAILABLE")
            if config.calendar_settings != settings or not self.is_connected:
                return unavailable("STORE_UNAVAILABLE")
            result = api.trading_calendar_query(
                route, route=route, venue=venue, kind=kind, product=product,
                contract=contract, trading_day=trading_day.isoformat(), timeout_seconds=5.0,
            )
            if type(result) is not GatewayCalendarQueryResult:
                raise ValueError("invalid Gateway calendar result")

            def plain(value):
                if isinstance(value, Mapping):
                    return {key: plain(item) for key, item in value.items()}
                if type(value) is tuple:
                    return [plain(item) for item in value]
                return value

            wire = {key: plain(getattr(result, key)) for key in result.__dataclass_fields__}
            checked = GatewayCalendarQueryResult.from_wire(wire)
            expected = {"mode": "SIMULATION_ONLY", "route": route, "venue": venue,
                        "kind": kind, "product": product, "contract": contract,
                        "trading_day": trading_day.isoformat()}
            if checked != result or dict(result.scope) != expected:
                raise ValueError("Gateway calendar scope changed")
            if config.calendar_settings != settings or not self.is_connected:
                return unavailable("STORE_CHANGED")
        except Exception:
            return unavailable("READ_UNAVAILABLE")
        with self._calendar_status_lock:
            if not (self._gateway_mode and not self._service_read_only and self._api is api
                    and self._gateway_strategy_config is config and self._gateway_run_lock is run_lock
                    and run_lock.held and self._gateway_pid == os.getpid() and not self._gateway_closed
                    and self._gateway_session_generation == generation
                    and self._calendar_status_generation == status_generation
                    and self._stream_generation == stream_generation
                    and tuple(self._sdk_exchanges) == routes and self._started and self._connected
                    and not self._calendar_status_transitions and not self._calendar_status_stopping):
                return unavailable("STORE_CHANGED")
            return result

    def trading_calendar_windows(self, route, *, venue, kind, product, contract, start_utc,
                                 end_utc, mode=None):
        """Read one explicitly enabled Gateway simulation range, with no local fallback."""
        def unavailable(reason):
            return _CalendarStatusUnavailable(reason=reason)

        if type(mode) is not str or mode != "SIMULATION_ONLY":
            return unavailable("SIMULATION_MODE_REQUIRED")
        pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        if any(type(value) is not str or re.fullmatch(pattern, value) is None
               for value in (route, venue, kind, product, contract)):
            return unavailable("INVALID_QUERY_SCOPE")
        if (type(start_utc) is not _dt.datetime or type(end_utc) is not _dt.datetime
                or start_utc.tzinfo is None or end_utc.tzinfo is None
                or start_utc.utcoffset() is None or end_utc.utcoffset() is None):
            return unavailable("INVALID_QUERY_RANGE")
        start_utc, end_utc = start_utc.astimezone(_UTC), end_utc.astimezone(_UTC)
        if not start_utc < end_utc or end_utc - start_utc > _dt.timedelta(days=366):
            return unavailable("INVALID_QUERY_RANGE")
        with self._calendar_status_lock:
            api, config, run_lock = self._api, self._gateway_strategy_config, self._gateway_run_lock
            generation, status_generation = self._gateway_session_generation, self._calendar_status_generation
            stream_generation, routes = self._stream_generation, tuple(self._sdk_exchanges)
            ready = (self._gateway_mode and not self._service_read_only and self._started
                     and self._connected and not self._gateway_closed and self._gateway_pid == os.getpid()
                     and api is not None and run_lock is not None and run_lock.held
                     and not self._calendar_status_transitions and not self._calendar_status_stopping)
        if route not in routes:
            return unavailable("ROUTE_UNCONFIGURED")
        if not ready:
            return unavailable("STORE_UNAVAILABLE")
        try:
            from bt_api_py.gateway_api import GatewayBtApi
            from bt_api_py.gateway_strategy_calendar import GatewayCalendarWindowsResult

            settings = None if config is None else config.calendar_settings
            if type(api) is not GatewayBtApi or settings is None or settings.range_read is not True:
                return unavailable("CAPABILITY_UNAVAILABLE")
            if config.calendar_settings != settings or not self.is_connected:
                return unavailable("STORE_UNAVAILABLE")
            start_text = start_utc.isoformat().replace("+00:00", "Z")
            end_text = end_utc.isoformat().replace("+00:00", "Z")
            result = api.trading_calendar_windows(
                route, route=route, venue=venue, kind=kind, product=product, contract=contract,
                start_utc=start_text, end_utc=end_text, timeout_seconds=5.0,
            )
            if type(result) is not GatewayCalendarWindowsResult:
                raise ValueError("invalid Gateway calendar range result")

            def plain(value):
                if isinstance(value, Mapping):
                    return {key: plain(item) for key, item in value.items()}
                if type(value) is tuple:
                    return [plain(item) for item in value]
                return value

            wire = {key: plain(getattr(result, key)) for key in result.__dataclass_fields__}
            checked = GatewayCalendarWindowsResult.from_wire(wire)
            expected = {"mode": "SIMULATION_ONLY", "route": route, "venue": venue,
                        "kind": kind, "product": product, "contract": contract,
                        "start_utc": start_text, "end_utc": end_text}
            if checked != result or dict(result.scope) != expected:
                raise ValueError("Gateway calendar range scope changed")
            if (config.calendar_settings != settings or settings.range_read is not True
                    or not self.is_connected):
                return unavailable("STORE_CHANGED")
        except Exception:
            return unavailable("READ_UNAVAILABLE")
        with self._calendar_status_lock:
            if not (self._gateway_mode and not self._service_read_only and self._api is api
                    and self._gateway_strategy_config is config and self._gateway_run_lock is run_lock
                    and run_lock.held and self._gateway_pid == os.getpid() and not self._gateway_closed
                    and self._gateway_session_generation == generation
                    and self._calendar_status_generation == status_generation
                    and self._stream_generation == stream_generation
                    and tuple(self._sdk_exchanges) == routes and self._started and self._connected
                    and not self._calendar_status_transitions and not self._calendar_status_stopping):
                return unavailable("STORE_CHANGED")
            return result

    def gateway_instrument_status(self, route, instrument, *, timeout_seconds=5.0):
        """Read one configured Gateway instrument diagnostic; never authorize trading."""
        from ..service.gateway_instrument_status import (
            detached_instrument, detached_result, unavailable, validate_timeout,
        )
        from bt_api_py.gateway_api import GatewayBtApi
        from bt_api_py.gateway_strategy_config import GatewayStrategyConfig

        key = detached_instrument(instrument)
        timeout = validate_timeout(timeout_seconds)
        if type(route) is not str or not route or route != route.strip():
            raise ValueError("INVALID_INSTRUMENT_STATUS_ROUTE")
        deadline = time.monotonic() + timeout
        try:
            with self._calendar_status_lock:
                api, config, run_lock = self._api, self._gateway_strategy_config, self._gateway_run_lock
                generation = self._gateway_session_generation
                status_generation = self._calendar_status_generation
                stream_generation = self._stream_generation
                routes = tuple(self._sdk_exchanges)
                ready = (self._gateway_mode and not self._service_read_only and self._started
                         and self._connected and not self._gateway_closed
                         and self._gateway_pid == os.getpid() and api is not None
                         and run_lock is not None and run_lock.held is True
                         and not self._calendar_status_transitions
                         and not self._calendar_status_stopping)
            if not ready or type(api) is not GatewayBtApi or type(config) is not GatewayStrategyConfig:
                return unavailable(key)
            config_snapshot = config.to_public_dict()
            if route not in routes or config.exchange_name != route:
                return unavailable(key, "SCOPE_DENIED")
            if sum(item == key for item in config.instruments_by_ref.values()) != 1:
                return unavailable(key, "SCOPE_DENIED")
            if "direct.instrument_status" not in config.requested_operations:
                return unavailable(key)
            if not self.is_connected:
                return unavailable(key)
            with self._calendar_status_lock:
                if not (self._gateway_mode and not self._service_read_only and self._api is api
                        and self._gateway_strategy_config is config and config.to_public_dict() == config_snapshot
                        and self._gateway_run_lock is run_lock and run_lock.held is True
                        and self._gateway_pid == os.getpid() and not self._gateway_closed
                        and self._gateway_session_generation == generation
                        and self._calendar_status_generation == status_generation
                        and self._stream_generation == stream_generation
                        and tuple(self._sdk_exchanges) == routes and self._started and self._connected
                        and not self._calendar_status_transitions and not self._calendar_status_stopping):
                    return unavailable(key)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return unavailable(key)
            result = detached_result(api.query_instrument_status(
                route, key, timeout_seconds=remaining), key)
            if time.monotonic() >= deadline or not self.is_connected:
                return unavailable(key)
            with self._calendar_status_lock:
                if not (self._gateway_mode and not self._service_read_only and self._api is api
                        and self._gateway_strategy_config is config and config.to_public_dict() == config_snapshot
                        and self._gateway_run_lock is run_lock and run_lock.held is True
                        and self._gateway_pid == os.getpid() and not self._gateway_closed
                        and self._gateway_session_generation == generation
                        and self._calendar_status_generation == status_generation
                        and self._stream_generation == stream_generation
                        and tuple(self._sdk_exchanges) == routes and self._started and self._connected
                        and not self._calendar_status_transitions and not self._calendar_status_stopping
                        and time.monotonic() < deadline):
                    return unavailable(key)
                return result
        except Exception:
            return unavailable(key)

    def configure_instrument_status_port(self, port):
        """Attach the explicit read-only instrument-status observation source.

        ``port`` must expose ``observation(scope)`` and return either ``None``
        (an explicit absence of an effective observation) or the provider's SDK
        ``InstrumentStatusView`` for exactly that scope.  ``None`` detaches it.
        This explicit call performs no I/O and never constructs a provider; an
        explicit port replaces any Store-attached route ports.  Separately, for
        an SDK direct-write Store with an explicit calendar route, the Store
        attaches the configured provider's read-only port once the facade is
        ready (G3).  Once attached, the direct-order gate consults it and fails
        closed; without any port the gate stays inactive and the existing
        direct-order path is unchanged.
        """
        if port is not None and not callable(getattr(port, "observation", None)):
            raise BtApiStoreError("instrument_status_port_invalid")
        with self._calendar_status_lock:
            self._instrument_status_port = port
            # An explicit port is authoritative; drop any Store-attached
            # route map so it cannot answer for the same routes instead.
            self._instrument_status_ports = {}
            self._instrument_status_ports_bound_for = None

    def instrument_status_source_configured(self):
        """Whether an explicit or Store-attached route status port is present."""
        with self._calendar_status_lock:
            return (
                getattr(self, "_instrument_status_port", None) is not None
                or bool(getattr(self, "_instrument_status_ports", None))
            )

    def _attach_configured_instrument_status_ports(self, api):
        """Attach one read-only provider port per explicitly configured route.

        Only the Store's own SDK direct-write mode with an explicit calendar
        route is wired: a provider view is a neutral observation fed by the
        native callback ingress, never a calendar, a guessed status or an
        account-wide value.  A route without a port, a provider that cannot
        answer, or any construction failure leaves every gate inactive rather
        than half-configured; an explicit port already set by the caller is
        never replaced.
        """
        if not (
            self._sdk_mode
            and not self._gateway_mode
            and not self._service_read_only
            and getattr(self, "_direct_write_mode", False)
        ):
            return
        routes = tuple(getattr(self, "_sdk_exchanges", {}) or {})
        local_routes = getattr(self, "_calendar_local_routes", frozenset())
        if not routes or not local_routes or set(routes) - set(local_routes):
            return
        with self._calendar_status_lock:
            if (
                self._instrument_status_port is not None
                or self._instrument_status_ports
                or self._instrument_status_ports_bound_for is api
            ):
                return
        try:
            coordinator = getattr(api, "direct_writes", None)
            if not callable(coordinator):
                return
            coordinator = coordinator()
            factory = getattr(coordinator, "instrument_status_port", None)
            if not callable(factory):
                return
            ports = {}
            for route in routes:
                port = factory(route)
                if port is None or not callable(getattr(port, "observation", None)):
                    return
                ports[route] = port
        except Exception:
            _safe_log("warning", "btapistore:instrument_status_port_unavailable")
            return
        with self._calendar_status_lock:
            if self._api is not api or self._instrument_status_port is not None:
                return
            if self._instrument_status_ports:
                return
            self._instrument_status_ports = ports
            self._instrument_status_ports_bound_for = api

    def instrument_status(
        self,
        route,
        *,
        venue,
        kind,
        product,
        instrument,
        trading_day,
        session_generation,
        window_id=None,
        at=None,
        observation=None,
        apply_result=None,
    ):
        """Compose one read-only per-instrument status for the exact scope (67.06).

        Delegates to the SDK's committed composition.  The Store supplies only
        its configured read-only calendar and one read-only observation port
        (an explicitly injected port, else the Store-attached port for this
        route); it writes nothing, sends no order, and contacts no provider
        beyond that port's pure read.  The answer is the SDK's frozen
        ``InstrumentStatusComposition`` or a Store-side
        ``_InstrumentStatusUnavailable``; it never authorizes trading and a
        missing answer is never reported as ``TRADABLE``.

        ``instrument`` is both the provider-native identity the observation is
        checked against and the exact calendar contract queried.  ``window_id``
        names the exact declared calendar window; when omitted, ``at`` (a
        timezone-aware instant) selects the unique published window containing
        it, so an open day without a selected window has no classified phase
        and composes ``UNKNOWN``.  The selection is a lookup of declared UTC
        half-open intervals, never an inferred session boundary.
        """

        def unavailable(reason):
            return _InstrumentStatusUnavailable(reason_code=reason)

        for value in (route, venue, kind, product, instrument):
            if type(value) is not str or not value or value != value.strip():
                return unavailable("INVALID_SCOPE")
        if type(session_generation) is not str or not session_generation:
            return unavailable("INVALID_SCOPE")
        if type(trading_day) is not _dt.date:
            return unavailable("INVALID_SCOPE")
        if window_id is not None and (
            type(window_id) is not str or not window_id or window_id != window_id.strip()
        ):
            return unavailable("INVALID_SCOPE")
        if at is not None and (
            type(at) is not _dt.datetime or at.tzinfo is None or at.utcoffset() is None
        ):
            return unavailable("INVALID_SCOPE")
        try:
            from bt_api_py.instrument_status_composition import (
                InstrumentStatusScope,
                calendar_answer_from_current_query,
                compose_instrument_status,
            )
        except ImportError:
            return unavailable("CAPABILITY_UNAVAILABLE")
        try:
            scope = InstrumentStatusScope(venue, instrument, trading_day, session_generation)
        except Exception:
            return unavailable("INVALID_SCOPE")
        with self._calendar_status_lock:
            configured_routes = tuple(self._sdk_exchanges)
            generation = self._calendar_status_generation
            stream_generation = self._stream_generation
            api = self._api
            port = getattr(self, "_instrument_status_port", None)
            ports = getattr(self, "_instrument_status_ports", None)
            routed_port = port if port is not None else (
                ports.get(route) if isinstance(ports, dict) else None
            )
            ready = (
                self._sdk_mode and not self._gateway_mode and not self._service_read_only
                and self._started and self._connected and self._sdk_configured
                and api is not None and not self._calendar_status_transitions
                and not self._calendar_status_stopping
            )
        if route not in configured_routes:
            return unavailable("ROUTE_UNCONFIGURED")
        if not ready:
            return unavailable("STORE_UNAVAILABLE")
        if observation is None and routed_port is not None:
            reader = getattr(routed_port, "observation", None)
            if not callable(reader):
                return unavailable("STATUS_PORT_UNAVAILABLE")
            try:
                observation = reader(scope)
            except Exception:
                return unavailable("STATUS_PORT_UNAVAILABLE")
        query = None
        query_reader = getattr(self, "trading_calendar_query", None)
        if callable(query_reader):
            try:
                query = query_reader(
                    route,
                    venue=venue,
                    kind=kind,
                    product=product,
                    contract=instrument,
                    trading_day=trading_day,
                    mode="SIMULATION_ONLY",
                )
            except Exception:
                query = None
        selected = window_id
        if selected is None and at is not None and query is not None:
            try:
                from bt_api_py.trading_calendar_runtime_status import (
                    TradingCalendarCurrentQuery,
                )

                if type(query) is TradingCalendarCurrentQuery and query.status == "COMPLETE":
                    moment = at.astimezone(_UTC)
                    matches = [
                        window.window_id
                        for window in query.windows
                        if type(getattr(window, "window_id", None)) is str
                        and window.start_utc <= moment < window.end_utc
                    ]
                    if len(matches) == 1:
                        selected = matches[0]
            except Exception:
                selected = None
        try:
            calendar = calendar_answer_from_current_query(query, scope=scope, window_id=selected)
            composition = compose_instrument_status(
                scope=scope,
                observation=observation,
                calendar=calendar,
                apply_result=apply_result,
            )
        except Exception:
            return unavailable("CAPABILITY_UNAVAILABLE")
        with self._calendar_status_lock:
            if not (
                generation == self._calendar_status_generation
                and stream_generation == self._stream_generation
                and self._api is api
                and tuple(self._sdk_exchanges) == configured_routes
                and getattr(self, "_instrument_status_ports", None) is ports
                and getattr(self, "_instrument_status_port", None) is port
            ):
                return unavailable("STORE_CHANGED")
        return composition

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

        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError(
                    "store_sdk_lifecycle_transition_in_progress"
                )
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
        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError(
                    "store_sdk_lifecycle_transition_in_progress"
                )
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
        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError(
                    "store_sdk_lifecycle_transition_in_progress"
                )
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    raise BtApiStoreError(
                        "store_sdk_lifecycle_transition_in_progress"
                    )
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
        """Leave the generation cache intact without refreshing during shutdown.

        Account-risk reads can require several authenticated venue requests.
        Shutdown preserves an already published snapshot and deliberately
        leaves a missing cache empty; after an owned API is closed, a later
        risk read fails closed without a transport.
        """
        if not self._sdk_owned_api or self._api is None:
            return
        # A cache hit is already retained by the generation-bound state owner.
        # A miss is intentionally not filled here: shutdown must not start a
        # provider read whose duration can exceed its close deadline.
        return

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
        if self._sdk_mode:
            # A borrowed facade remains caller-owned after Store stop. Keep
            # risk reads local once its Store generation is retired, even if
            # the facade object itself is still present.
            borrowed_store_stopped = (
                not self._sdk_owned_api
                and not self._started
                and self._shutdown_state == "PASS"
            )
            if (
                borrowed_store_stopped
                or self._sdk_borrowed_event_lifecycle_error() is not None
            ):
                return self._cached_account_risk_unavailable()
            with self._sdk_api_activity() as admitted:
                if not admitted:
                    return self._cached_account_risk_unavailable()
                return self._read_account_risk_snapshot(self._api)
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
                self._live_bar_queue.enqueue(
                    str(dataname), self._copy_or_normalize_bar(bar)
                )

    def _enqueue_live_bar(self, symbol: str, bar: Any) -> None:
        """Append one copied bar to the Backtrader-owned bounded queue."""
        accepted = self._live_bar_queue.enqueue(
            symbol, bar, generation=self._stream_generation
        )
        if not accepted:
            self._record_market_drop(
                bar,
                "store_live_bar_start_aborted",
                safety_impact="bar_rejected_from_failed_store_generation",
                symbol=symbol,
                kind="bar",
            )
            self._mark_live_bar_queue_stale(
                symbol, "store_live_bar_start_aborted"
            )

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

    def _begin_sdk_event_drain(self) -> bool:
        """Reserve the Store's bounded SDK-poll lease without holding it on I/O."""
        if not self._sdk_mode:
            return False
        with self._sdk_start_state_lock:
            if (
                self._sdk_start_in_progress
                or self._sdk_stop_in_progress
                or self._sdk_event_drain_in_progress
            ):
                return False
            borrowed_event_error = self._sdk_borrowed_event_lifecycle_error()
            if borrowed_event_error is not None:
                raise BtApiStoreError(borrowed_event_error)
            self._sdk_event_batch_continuation_pending = False
            self._sdk_event_drain_in_progress = True
            self._sdk_event_drain_owner_thread_id = threading.get_ident()
        return True

    def _finish_sdk_event_drain(self) -> bool:
        """Atomically take this drain's wake and release its bounded poll lease."""
        owner_thread_id = threading.get_ident()
        with self._sdk_start_state_lock:
            if (
                not self._sdk_event_drain_in_progress
                or self._sdk_event_drain_owner_thread_id != owner_thread_id
            ):
                raise BtApiStoreError("store_sdk_event_drain_lease_owner_mismatch")
            continuation_pending = self._sdk_event_batch_continuation_pending
            self._sdk_event_batch_continuation_pending = False
            self._sdk_event_drain_in_progress = False
            self._sdk_event_drain_owner_thread_id = None
            self._sdk_start_state_lock.notify_all()
            return continuation_pending

    def _drain_sdk_events(self):
        if not self._sdk_mode:
            return
        if not self._begin_sdk_event_drain():
            return
        try:
            self._drain_sdk_events_locked()
        finally:
            # Detach this drain's marker under the lease lock. A following
            # drain can start as soon as _finish returns and must not clear or
            # steal the wake associated with this completed result.
            continuation_pending = self._finish_sdk_event_drain()
            if continuation_pending:
                # Wake only after releasing the drain lease.  The notifier may
                # run callbacks synchronously; signaling under the lease could
                # make an immediate bounded retry lose its only wakeup.
                try:
                    self._signal_live_bar_event()
                except Exception:
                    # The SDK batch has already been ACKed.  Preserve that
                    # outcome and leave a finite diagnostic if an engine wake
                    # callback fails; never turn it into a dispatch retry.
                    self._command_health[
                        "sdk_event_batch_continuation_wake_failed"
                    ] += 1

    def _drain_sdk_events_locked(self):
        """Poll unlocked, then dispatch each ordered venue batch under lock."""
        # Resolve the complete event projection contract before poll_events can
        # consume a batch that this Store cannot dispatch.
        event_header = _require_store_event_dispatch_contracts(
            missing_dependency_error_type=BtApiMissingDependencyError,
        )
        if self._sdk_event_batch_handoff:
            coordinator = self._sdk_event_batch_coordinator
            if coordinator is None or coordinator.state != "claimed":
                # Never switch to destructive legacy polling after an opt-in
                # claim attempt. Registration is irreversible at Store scope.
                self._command_health["sdk_event_batch_consumer_unavailable"] += 1
                self._shutdown_state = "INCOMPLETE"
                raise BtApiStoreError("store_sdk_event_batch_consumer_unavailable")
            if len(self._sdk_exchanges) != 1:
                self._command_health["sdk_event_batch_route_configuration_changed"] += 1
                self._shutdown_state = "INCOMPLETE"
                raise BtApiStoreError("store_sdk_event_batch_route_configuration_changed")
            venue = next(iter(self._sdk_exchanges))

            def preflight(batch_venue, events):
                if batch_venue != venue:
                    raise BtApiStoreError("store_sdk_event_batch_route_mismatch")
                with self._sdk_event_drain_lock:
                    _preflight_store_sdk_event_batch(
                        self,
                        venue,
                        events,
                        error_type=BtApiStoreError,
                        event_header=event_header,
                    )

            def dispatch(batch_venue, event):
                if batch_venue != venue:
                    raise BtApiStoreError("store_sdk_event_batch_route_mismatch")
                with self._sdk_event_drain_lock:
                    _dispatch_store_sdk_event_locked(
                        self,
                        venue,
                        event,
                        error_type=BtApiStoreError,
                        event_header=event_header,
                    )

            try:
                result = coordinator.drain_once(
                    dispatch,
                    preflight_events=preflight,
                )
            except StoreEventBatchError as exc:
                self._command_health["sdk_event_batch_drain_failed"] += 1
                self._shutdown_state = "INCOMPLETE"
                raise BtApiStoreError(
                    "store_sdk_event_batch_{}_{}".format(exc.phase, exc.code)
                ) from None
            except BaseException:
                # The coordinator records dispatch/ACK uncertainty before it
                # re-raises process-control exceptions. Preserve that exact
                # exception while making the Store health projection fail closed.
                if coordinator.state != "claimed":
                    self._command_health["sdk_event_batch_drain_interrupted"] += 1
                    self._shutdown_state = "INCOMPLETE"
                raise

            self._sdk_event_batch_continuation_pending = bool(
                result.continuation_required
            )
            if result.status == "raw_budget_blocked":
                self._command_health["sdk_event_batch_raw_budget_blocked"] += 1
            return

        for venue in self._sdk_exchanges:
            # poll_events() also advances execution-session reconciliation and
            # may perform synchronous provider I/O. The lifecycle lease keeps
            # start/stop out while this call runs; no Store lock spans it.
            events = _poll_store_sdk_events(self, venue)
            with self._sdk_event_drain_lock:
                _dispatch_store_sdk_events_locked(
                    self,
                    venue,
                    events,
                    error_type=BtApiStoreError,
                    missing_dependency_error_type=BtApiMissingDependencyError,
                    event_header=event_header,
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
        api_factory = self._api_cls
        assembly = DirectApiAssembly.from_options(
            options=options,
            exchange_kwargs=self._sdk_direct_exchange_kwargs,
            execution_config=execution_config,
            api_factory=api_factory,
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
            "event_batch_handoff",
            *DIRECT_EXECUTION_CONFIG_KEYS,
        ):
            self._config.pop(key, None)
            self._api_kwargs.pop(key, None)
        options.clear()
        execution_config.clear()
        return assembly

    def _ensure_api_ready(self):
        """Ensure the Store-bound facade is ready through its lifecycle bridge."""
        # Centralize readiness so callers cannot rebind this Store's notifier
        # after a borrowed SDK generation or read-only service session stops.
        # This lease covers readiness only; direct API operations hold an outer
        # activity lease through their complete read and local projection.
        with self._sdk_api_activity() as admitted:
            if not admitted:
                raise BtApiStoreError("store_sdk_lifecycle_transition_in_progress")
            return self._ensure_api_ready_under_activity()

    def _ensure_api_ready_under_activity(self):
        """Perform API readiness while the caller owns a Store activity lease."""
        if self._gateway_mode:
            if not self._started or not self.is_connected:
                raise BtApiStoreError("GATEWAY_SESSION_UNAVAILABLE")
            return self._api
        if self._sdk_event_batch_handoff:
            # Fail before facade construction/connect can start an SDK source.
            # This resolver imports and checks the public event dispatch
            # contracts only; it performs no provider or transport operation.
            _require_store_event_dispatch_contracts(
                missing_dependency_error_type=BtApiMissingDependencyError,
            )
        api = _ensure_store_api_ready(
            self, error_type=BtApiStoreError,
            gateway_entrypoint=_legacy_gateway_entrypoint,
            gateway_error_type=LegacyGatewayMigrationRequiredError,
            placeholder_providers=_PLACEHOLDER_PROVIDERS,
            provider_not_implemented_error_type=BtApiProviderNotImplementedError,
            safe_log=_safe_log,
        )
        # Iteration 67 G8: mirror the explicit calendar routes into a facade
        # this Store owns.  A borrowed/factory facade is never rewritten.
        self._configure_owned_facade_calendar(api)
        # Iteration 67 G3: once the facade is ready, attach the configured
        # route's read-only provider status port.  This is the production
        # caller of the CTP ingress -> ledger -> SDK composition chain; absent
        # calendar configuration leaves the direct-order gate unchanged.
        self._attach_configured_instrument_status_ports(api)
        self._ensure_sdk_event_batch_consumer_claimed()
        return api

    def _ensure_sdk_event_batch_consumer_claimed(self) -> None:
        """Claim the sole opt-in route before any Store legacy poll can run."""
        if not self._sdk_event_batch_handoff:
            return
        with self._sdk_event_batch_claim_lock:
            self._claim_sdk_event_batch_consumer_locked()

    def _claim_sdk_event_batch_consumer_locked(self) -> None:
        """Serialize Store-local claim creation and the one-way SDK call."""
        if not self._sdk_mode or self._api is None or len(self._sdk_exchanges) != 1:
            raise BtApiStoreError("store_sdk_event_batch_configuration_invalid")
        coordinator = self._sdk_event_batch_coordinator
        if coordinator is None or coordinator.state == "new":
            # Resolve every dependency needed to validate and dispatch a batch
            # before taking the SDK's irreversible single-consumer claim.
            # This resolver imports only the public event contracts; it does
            # not poll, connect, or call a provider transport.
            _require_store_event_dispatch_contracts(
                missing_dependency_error_type=BtApiMissingDependencyError,
            )
            required_methods = (
                "register_event_consumer",
                "poll_event_batch",
                "ack_event_batch",
            )
            if any(
                not callable(getattr(self._api, name, None))
                for name in required_methods
            ):
                raise BtApiMissingDependencyError(
                    "bt_api_py event batch handoff contract is required"
                )
        venue = next(iter(self._sdk_exchanges))
        if coordinator is None:
            coalesce = (
                self._sdk_coalesce_market_snapshots
                if self.uses_async_commands
                else ("orderbook",)
            )
            coordinator = StoreEventBatchCoordinator(
                self._api,
                venue,
                max_raw_items=self._sdk_event_batch_event_limit,
                max_events=self._sdk_event_batch_event_limit,
                max_scan_items=self._sdk_event_batch_scan_limit,
                coalesce_market_snapshots=coalesce,
            )
            # Publish the coordinator before the irreversible SDK claim.  If
            # claim raises after taking effect, all later paths see and retain
            # its unknown state instead of falling back to poll_events.
            self._sdk_event_batch_coordinator = coordinator
        if coordinator.api is not self._api or coordinator.venue != venue:
            raise BtApiStoreError("store_sdk_event_batch_api_binding_changed")
        if coordinator.state == "new":
            try:
                coordinator.claim()
            except StoreEventBatchError as exc:
                self._command_health["sdk_event_batch_claim_failed"] += 1
                self._shutdown_state = "INCOMPLETE"
                raise BtApiStoreError(
                    "store_sdk_event_batch_claim_" + exc.code
                ) from None
            except BaseException:
                # The SDK call may have claimed before control returned to the
                # Store. Keep its unknown token state and propagate unchanged.
                if coordinator.state != "new":
                    self._command_health["sdk_event_batch_claim_interrupted"] += 1
                    self._shutdown_state = "INCOMPLETE"
                raise
        if coordinator.state != "claimed":
            raise BtApiStoreError("store_sdk_event_batch_consumer_fail_closed")

    def _sdk_event_batch_stop_unproven(self) -> bool:
        """Whether an irreversible batch claim still lacks producer-stop proof."""
        coordinator = self._sdk_event_batch_coordinator
        return bool(
            self._sdk_event_batch_handoff
            and coordinator is not None
            and coordinator.state not in {"new", "claim_blocked"}
        )

    def _retain_unproven_sdk_event_batch(self) -> None:
        """Keep the route, waker, and lease intact when source stop is unknown."""
        with self._sdk_start_state_lock:
            self._sdk_event_batch_stop_requested = True
        self._shutdown_state = "INCOMPLETE"
        self._command_health["stop_event_batch_producer_quiescence_unproven"] += 1
        self.emit_runtime_event(
            "store_disconnect_incomplete",
            status="incomplete",
            details={"reason": "event_batch_producer_quiescence_unproven"},
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
