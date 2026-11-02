"""Read-only service backend for the 014_2 standard live entry.

The backend is selected explicitly by ``live_adapter.backend: service``.  Its
caller supplies the ordinary SDK ClientConfig plus trusted local identity,
scope and Curve-key *references*.  Secrets are read only from named process
environment variables; the direct SimNow ``.env`` loader is never used here.

This consumer can validate provider/session identity and preserve CTP ticks,
but the current CTP contract does not qualify a cross-process event/receive
clock mapping.  Accordingly, the normal Cerebro path always reports BLOCKED
until that qualification exists; source identity or a matching clock-domain
string is not treated as clock calibration or freshness evidence.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


EXIT_BLOCKED = 2
EXIT_UNKNOWN = 3
_LEG_NAMES = ("future", "call", "put")


class ServiceBackendError(RuntimeError):
    """Finite local refusal that never contains operator or provider values."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.isascii() or not code:
            raise ValueError("code must be a finite ASCII identifier")
        self.code = code
        super().__init__(code)


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ServiceBackendError(f"SERVICE_CONFIG_{field.upper()}_INVALID")
    return value


def _mapping(value: Any, field: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ServiceBackendError(f"SERVICE_CONFIG_{field.upper()}_INVALID")
    return value


def _service_document(live: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        type(live.get("schema_version")) is not int
        or live.get("schema_version") != 1
        or live.get("venue") != "simnow"
    ):
        raise ServiceBackendError("SERVICE_LIVE_ADAPTER_UNSUPPORTED")
    policy = live.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allow_write") is not False:
        raise ServiceBackendError("SERVICE_WRITE_POLICY_INVALID")
    candidate = live.get("live_candidate")
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("contracts"), Mapping):
        raise ServiceBackendError("SERVICE_LIVE_CANDIDATE_INVALID")
    service = live.get("service")
    if not isinstance(service, Mapping) or set(service) != {
        "client_config",
        "identity",
        "service_principals",
        "curve_key_envs",
        "account",
        "market",
    }:
        raise ServiceBackendError("SERVICE_CONFIG_INVALID")
    return service


def _account_resources(account: Mapping[str, Any]):
    from bt_api_py.service_contracts  import AccountKey, AccountResourceKey

    account = _mapping(
        account,
        "account",
        {
            "mount",
            "account_ref",
            "key",
            "required_coverage",
            "resource_by_leg",
            "valuation_currency",
            "position_mode",
            "qty_unit",
        },
    )
    key_raw = _mapping(
        account["key"],
        "account_key",
        {"provider", "venue", "environment", "account_id", "subaccount_id"},
    )
    try:
        key = AccountKey(**dict(key_raw))
    except (TypeError, ValueError):
        raise ServiceBackendError("SERVICE_ACCOUNT_KEY_INVALID") from None
    if key.provider != "ctp":
        raise ServiceBackendError("SERVICE_ACCOUNT_PROVIDER_INVALID")

    raw_coverage = account["required_coverage"]
    if type(raw_coverage) is not list or not raw_coverage:
        raise ServiceBackendError("SERVICE_ACCOUNT_COVERAGE_INVALID")
    try:
        coverage = tuple(
            AccountResourceKey(**dict(_mapping(item, "coverage", {"product_type", "margin_pool"})))
            for item in raw_coverage
        )
    except (TypeError, ValueError):
        raise ServiceBackendError("SERVICE_ACCOUNT_COVERAGE_INVALID") from None
    if len(set(coverage)) != len(coverage):
        raise ServiceBackendError("SERVICE_ACCOUNT_COVERAGE_DUPLICATE")

    raw_by_leg = _mapping(
        account["resource_by_leg"], "resource_by_leg", set(_LEG_NAMES)
    )
    try:
        by_leg = {
            leg: AccountResourceKey(
                **dict(_mapping(raw_by_leg[leg], "resource", {"product_type", "margin_pool"}))
            )
            for leg in _LEG_NAMES
        }
    except (TypeError, ValueError):
        raise ServiceBackendError("SERVICE_ACCOUNT_RESOURCE_INVALID") from None
    if any(resource not in coverage for resource in by_leg.values()):
        raise ServiceBackendError("SERVICE_ACCOUNT_RESOURCE_OUTSIDE_COVERAGE")
    return key, coverage, by_leg






def _positive_decimal(value: Any) -> Decimal:
    if type(value) is not str:
        raise ServiceBackendError("SERVICE_METADATA_INVALID")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ServiceBackendError("SERVICE_METADATA_INVALID") from None
    try:
        numeric = float(parsed)
    except (OverflowError, ValueError):
        raise ServiceBackendError("SERVICE_METADATA_INVALID") from None
    if not parsed.is_finite() or parsed <= 0 or not math.isfinite(numeric) or numeric <= 0:
        raise ServiceBackendError("SERVICE_METADATA_INVALID") from None
    return parsed


def _metadata_set(account_client: Any, view: Any, contracts: Mapping[str, Any]):
    metadata_type = account_client.instrument_metadata_type
    if not isinstance(metadata_type, type):
        raise ServiceBackendError("SERVICE_METADATA_TYPE_UNAVAILABLE")

    metadata = {}
    for leg in _LEG_NAMES:
        full_symbol = str(contracts.get(leg) or "")
        exchange, separator, instrument_id = full_symbol.partition(".")
        if not separator or not exchange or not instrument_id:
            raise ServiceBackendError("SERVICE_CONTRACT_IDENTITY_INVALID")
        try:
            item = account_client.instrument_metadata(instrument_id, exchange)
        except Exception as exc:
            raise ServiceBackendError(_safe_code(exc, "SERVICE_INSTRUMENT_METADATA_READ_FAILED")) from None
        if type(item) is not metadata_type:
            raise ServiceBackendError("SERVICE_METADATA_TYPE_INVALID")
        if (
            item.instrument_id != instrument_id
            or item.exchange_id != exchange
            or item.account_session_generation != view.session_generation
            or item.account_fingerprint == ""
            or item.source != "ctp.native.instruments"
            or type(item.source_connection_generation) is not int
            or item.source_connection_generation <= 0
        ):
            raise ServiceBackendError("SERVICE_METADATA_IDENTITY_MISMATCH")
        _positive_decimal(item.price_tick)
        if type(item.volume_multiple) is not int or item.volume_multiple <= 0:
            raise ServiceBackendError("SERVICE_METADATA_INVALID")
        metadata[leg] = item

    first = metadata[_LEG_NAMES[0]]
    if any(
        item.account_session_generation != first.account_session_generation
        or item.account_fingerprint != first.account_fingerprint
        or item.trading_day != first.trading_day
        or item.source_connection_generation != first.source_connection_generation
        for item in metadata.values()
    ):
        raise ServiceBackendError("SERVICE_METADATA_SESSION_CHANGED")
    multiplier = {item.volume_multiple for item in metadata.values()}
    if len(multiplier) != 1:
        raise ServiceBackendError("SERVICE_VOLUME_MULTIPLIER_MISMATCH")

    # The configured candidate remains authoritative for strategy economics.
    # The caller separately checks that its declared multiplier agrees with
    # all three provider-issued contract rows before any market subscription.
    return metadata


def _validate_candidate_multiplier(
    candidate: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    fallback_candidate: Mapping[str, Any] | None = None,
) -> None:
    """Require the strategy's declared contract multiplier to match all legs."""
    raw_multiplier = candidate.get(
        "multiplier",
        fallback_candidate.get("multiplier") if isinstance(fallback_candidate, Mapping) else None,
    )
    if type(raw_multiplier) not in {int, str}:
        raise ServiceBackendError("SERVICE_CANDIDATE_MULTIPLIER_INVALID")
    try:
        configured = Decimal(raw_multiplier)
    except (InvalidOperation, ValueError):
        raise ServiceBackendError("SERVICE_CANDIDATE_MULTIPLIER_INVALID") from None
    if not configured.is_finite() or configured <= 0:
        raise ServiceBackendError("SERVICE_CANDIDATE_MULTIPLIER_INVALID")
    if set(metadata) != set(_LEG_NAMES) or any(
        type(metadata[leg].volume_multiple) is not int
        or Decimal(metadata[leg].volume_multiple) != configured
        for leg in _LEG_NAMES
    ):
        raise ServiceBackendError("SERVICE_VOLUME_MULTIPLIER_MISMATCH")


def _validate_shared_market_source_descriptors(descriptors: Mapping[str, Any]) -> str:
    """Require the three subscribed legs to report one source identity.

    These fields bind source/session identity only.  Equality does not qualify
    cross-process receive-clock mapping, event-time calibration, or freshness.
    """
    from bt_api_py.service_contracts import MarketSourceDescriptor

    if not isinstance(descriptors, Mapping) or set(descriptors) != set(_LEG_NAMES):
        raise ServiceBackendError("SERVICE_MARKET_SOURCE_SESSION_MISMATCH")
    if any(type(value) is not MarketSourceDescriptor for value in descriptors.values()):
        raise ServiceBackendError("SERVICE_MARKET_SOURCE_SESSION_MISMATCH")
    source_domains = {item.clock_domain_id for item in descriptors.values()}
    source_sessions = {item.clock_source_session_id for item in descriptors.values()}
    source_generations = {item.connection_generation for item in descriptors.values()}
    source_clocks = {item.clock_source for item in descriptors.values()}
    if any(
        len(values) != 1
        for values in (source_domains, source_sessions, source_generations, source_clocks)
    ):
        raise ServiceBackendError("SERVICE_MARKET_SOURCE_SESSION_MISMATCH")
    return next(iter(source_domains))


def _safe_code(exc: BaseException, default: str) -> str:
    code = getattr(exc, "code", None)
    if type(code) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", code):
        return code
    return default


def _stop_broker_and_store(broker: Any, store: Any, timeout: float):
    """Stop the broker, then explicitly close the Store if it did not prove so.

    Cerebro may fail while constructing a Strategy, before it ever starts the
    Broker. In that case a market-data-only Broker can return its initial empty
    shutdown summary without stopping its already-connected read-only proxy.
    The Store remains the owner of that proxy and must still perform its normal
    bounded stop path before the shared runtime closes.
    """

    cleanup_errors = []
    broker_health = None
    if broker is not None:
        try:
            broker_health = broker.stop()
        except Exception as exc:
            cleanup_errors.append(f"broker_stop:{_safe_code(exc, type(exc).__name__)}")

    store_health = None
    store_confirmed = (
        isinstance(broker_health, Mapping)
        and broker_health.get("store_shutdown_state") == "PASS"
    )
    if store is not None and not store_confirmed:
        try:
            store_health = store.stop(timeout=timeout)
        except Exception as exc:
            cleanup_errors.append(f"store_stop:{_safe_code(exc, type(exc).__name__)}")
        else:
            store_confirmed = (
                isinstance(store_health, Mapping)
                and store_health.get("shutdown_state") == "PASS"
            )
    if (broker is not None or store is not None) and not store_confirmed:
        cleanup_errors.append("store_shutdown_unconfirmed")
    return broker_health, store_health, cleanup_errors


def _source_roots():
    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser().resolve()
    candidates = (
        root,
        root / "bt_api" / "bt_api_base" / "src",
        root / "bt_api" / "bt_api_transport_zmq" / "src",
    )
    for path in reversed(candidates):
        if path.is_dir():
            text = str(path)
            if text in os.sys.path:
                os.sys.path.remove(text)
            os.sys.path.insert(0, text)
    return root


def _require_dev_origin(module: Any, root: Path) -> None:
    origin = getattr(module, "__file__", None)
    if not origin:
        raise ServiceBackendError("SERVICE_SDK_ORIGIN_UNAVAILABLE")
    try:
        Path(origin).resolve().relative_to(root)
    except (OSError, ValueError):
        raise ServiceBackendError("SERVICE_SDK_ORIGIN_NOT_DEV_SOURCE") from None


def _load_service_dependencies(root: Path):
    import bt_api_base
    import bt_api_py
    import bt_api_transport_zmq

    for module in (bt_api_base, bt_api_py, bt_api_transport_zmq):
        _require_dev_origin(module, root)
    return bt_api_base, bt_api_py, bt_api_transport_zmq


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
        encoding="utf-8",
    )


def run_live_service(args: Any, raw_config: Mapping[str, Any], decision: Any, runner_module: Any) -> int:
    """Fail closed until the SDK exposes a connected neutral tick/clock contract.

    This service backend requires tick data to run its four-leg live strategy.
    Source identity alone does not establish a usable data clock, and the SDK
    currently exposes no bound neutral market-event projection to this caller.
    Do not start runtimes, read accounts, subscribe, or fall back to another
    feed while that contract is unavailable.
    """
    decision_evidence = decision.as_evidence() if decision is not None else {}
    if getattr(args, "allow_write", False):
        reason = "write_tier_not_implemented_for_decision_only_strategy"
    elif os.sys.version_info[:2] != (3, 11):
        reason = "live_tier_requires_python_3_11"
    else:
        reason = "service_market_tick_clock_binding_unavailable"

    runner_module._json_print(
        {
            "status": "BLOCKED",
            "mode": "live",
            "backend": "service",
            "reason": reason,
            "service_market_capability": "TICK_DATA_CLOCK_BINDING_UNAVAILABLE",
            "service_clock_qualification": "NOT_QUALIFIED",
            "service_clock_reason": "sdk_neutral_market_event_clock_binding_unavailable",
            "source_identity_is_clock_qualification": False,
            "provider_operations": {
                "account_refresh": 0,
                "market_subscriptions": 0,
            },
            "external_request_counts": {"order_write": 0},
            "entry_tier": dict(decision_evidence),
            "write_grant_result": "refused_no_order_path_by_contract",
        }
    )
    return EXIT_BLOCKED
