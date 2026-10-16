"""Scoped, read-only sessions for the examples' normal SDK observation paths.

The caller owns the Gateway hosts.  This module owns only SDK client facades,
their read-only Store bridge when an exact binding is available, and the
client runtime created from the caller's explicit service configuration.
Provider identity and source descriptors are observations; they do not prove
clock calibration, freshness, or write authority.
"""

from __future__ import annotations

import copy
import os
import re
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from types import MappingProxyType
from typing import Any


class ServiceObservationError(RuntimeError):
    """Finite errors that never include configuration, credentials, or rows."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
            raise ValueError("code must be a finite uppercase ASCII identifier")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ServiceObservationInstrument:
    """One explicitly named read subscription and its optional account mapping.

    ``market_key`` may be a typed ``MarketSubscriptionKey`` or its exact
    ``to_dict()`` shape.  For a CTP quote, callers may instead provide the
    bare ``instrument_id`` and ``exchange_id``; the helper first reads typed
    account-session metadata and derives the market key from those facts and
    the configured source/entitlement references.

    ``resource`` is an explicit ``AccountResourceKey`` or its exact two-field
    mapping.  It is never inferred from a market instrument or provider
    metadata.
    """

    dataname: str
    market_key: Any = None
    instrument_id: str | None = None
    exchange_id: str | None = None
    resource: Any = None
    qty_unit: str | None = None
    quantity_multiplier: str = "1"
    max_event_age_seconds: str = "2"
    require_source_descriptor: bool | None = None

    def __post_init__(self) -> None:
        if type(self.dataname) is not str or not self.dataname or self.dataname != self.dataname.strip():
            raise ValueError("dataname must be non-empty text")
        if self.market_key is None:
            if type(self.instrument_id) is not str or not self.instrument_id or self.instrument_id != self.instrument_id.strip():
                raise ValueError("instrument_id is required when market_key is absent")
            if type(self.exchange_id) is not str or not self.exchange_id or self.exchange_id != self.exchange_id.strip():
                raise ValueError("exchange_id is required when market_key is absent")
        elif self.instrument_id is not None or self.exchange_id is not None:
            raise ValueError("market_key and CTP metadata identity are mutually exclusive")
        if self.qty_unit is not None and (
            type(self.qty_unit) is not str or not self.qty_unit or self.qty_unit != self.qty_unit.strip()
        ):
            raise ValueError("qty_unit must be non-empty text when supplied")
        if type(self.quantity_multiplier) is not str:
            raise ValueError("quantity_multiplier must be text")
        if type(self.max_event_age_seconds) is not str:
            raise ValueError("max_event_age_seconds must be text")
        if self.require_source_descriptor is not None and type(self.require_source_descriptor) is not bool:
            raise ValueError("require_source_descriptor must be bool or None")


_CLEANUP_KEEPALIVE: list[tuple[Any, ...]] = []
_KEEPALIVE_LOCK = threading.Lock()
_ACCOUNT_OPERATIONS = frozenset({"account.snapshot", "account.instrument_metadata"})
_MARKET_OPERATIONS = frozenset(
    {"market.subscribe", "market.unsubscribe", "market.snapshot", "market.head", "market.read_after"}
)
_SERVICE_FIELDS = frozenset(
    {"client_config", "identity", "service_principals", "curve_key_envs", "account", "market"}
)
_ACCOUNT_FIELDS = frozenset(
    {
        "mount",
        "account_ref",
        "key",
        "required_coverage",
        "resource_by_leg",
        "valuation_currency",
        "position_mode",
        "qty_unit",
    }
)
_MARKET_FIELDS = frozenset({"mount", "source_ref", "entitlement_ref"})
_SERVICE_FILE_MAX_BYTES = 1024 * 1024


def _mapping(value: Any, code: str, fields: set[str] | frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ServiceObservationError(code)
    return value


def _text(value: Any, code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ServiceObservationError(code)
    return value


def _source_roots(root_override: str | os.PathLike[str] | None = None) -> Path:
    root_value = root_override or os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py"
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ServiceObservationError("SERVICE_SDK_SOURCE_ROOT_INVALID") from None
    candidates = (
        root,
        root / "bt_api" / "bt_api_base" / "src",
        root / "bt_api" / "bt_api_transport_zmq" / "src",
    )
    for path in reversed(candidates):
        if path.is_dir():
            text = str(path)
            if text in sys.path:
                sys.path.remove(text)
            sys.path.insert(0, text)
    return root


def _require_dev_origin(module: Any, root: Path) -> None:
    origin = getattr(module, "__file__", None)
    if not origin:
        raise ServiceObservationError("SERVICE_SDK_ORIGIN_UNAVAILABLE")
    try:
        Path(origin).resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ServiceObservationError("SERVICE_SDK_ORIGIN_NOT_DEV_SOURCE") from None


def _load_sdk(root: Path, *, include_ctp: bool = False):
    import bt_api_base
    import bt_api_base.account_protocol
    import bt_api_base.market_protocol
    import bt_api_base.service_protocol
    import bt_api_py
    import bt_api_py.service_account
    import bt_api_py.service_config
    import bt_api_py.service_market
    import bt_api_py.service_runtime
    import bt_api_transport_zmq

    modules = [
        bt_api_base,
        bt_api_base.account_protocol,
        bt_api_base.market_protocol,
        bt_api_base.service_protocol,
        bt_api_py,
        bt_api_py.service_account,
        bt_api_py.service_config,
        bt_api_py.service_market,
        bt_api_py.service_runtime,
        bt_api_transport_zmq,
    ]
    if include_ctp:
        import bt_api_ctp

        modules.append(bt_api_ctp)
    for module in modules:
        _require_dev_origin(module, root)
    return bt_api_base


def account_resource_key(value: Any, *, sdk_root: str | os.PathLike[str] | None = None):
    """Build an exact dev-source AccountResourceKey without caller path setup."""
    root = _source_roots(sdk_root)
    _load_sdk(root)
    from bt_api_base.account_protocol import AccountResourceKey

    try:
        if type(value) is AccountResourceKey:
            return value
        return AccountResourceKey.from_dict(value)
    except ServiceObservationError:
        raise
    except Exception:
        raise ServiceObservationError("SERVICE_ACCOUNT_RESOURCE_INVALID") from None


def market_subscription_key(value: Any, *, sdk_root: str | os.PathLike[str] | None = None):
    """Build an exact dev-source MarketSubscriptionKey without caller imports."""
    root = _source_roots(sdk_root)
    _load_sdk(root)
    from bt_api_base.market_protocol import MarketSubscriptionKey

    try:
        if type(value) is MarketSubscriptionKey:
            return value
        return MarketSubscriptionKey.from_dict(value)
    except ServiceObservationError:
        raise
    except Exception:
        raise ServiceObservationError("SERVICE_MARKET_KEY_INVALID") from None


def load_service_observation_config(path: str | os.PathLike[str]) -> Mapping[str, Any]:
    """Read one explicit service-only YAML/JSON file without echoing values.

    The file may contain the service mapping directly or as its sole ``service``
    member. Credential material is not accepted by this format; callers provide
    CURVE keys through named process environment variables.
    """

    if not isinstance(path, (str, os.PathLike)) or isinstance(path, bool):
        raise ServiceObservationError("SERVICE_CONFIG_PATH_INVALID")
    try:
        config_path = Path(path).expanduser().resolve(strict=True)
        if not config_path.is_file():
            raise OSError
        size = config_path.stat().st_size
        if type(size) is not int or size <= 0 or size > _SERVICE_FILE_MAX_BYTES:
            raise ServiceObservationError("SERVICE_CONFIG_SIZE_INVALID")
        raw = config_path.read_bytes()
        if len(raw) != size:
            raise ServiceObservationError("SERVICE_CONFIG_READ_INCOMPLETE")
        text = raw.decode("utf-8", errors="strict")
    except ServiceObservationError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        raise ServiceObservationError("SERVICE_CONFIG_UNAVAILABLE") from None
    try:
        import yaml

        loaded = yaml.safe_load(text)
    except Exception:
        raise ServiceObservationError("SERVICE_CONFIG_PARSE_FAILED") from None
    if not isinstance(loaded, Mapping):
        raise ServiceObservationError("SERVICE_CONFIG_INVALID")
    if set(loaded) == {"service"}:
        loaded = loaded["service"]
    service = _mapping(loaded, "SERVICE_CONFIG_INVALID", _SERVICE_FIELDS)
    return MappingProxyType(dict(service))


def _build_runtime(
    service: Mapping[str, Any],
    env: Mapping[str, str],
    root: Path,
    *,
    require_instrument_metadata: bool,
):
    base = _load_sdk(root)
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory

    try:
        parsed = parse_client_config(copy.deepcopy(service["client_config"]))
        public = parsed.to_public_dict()
    except Exception:
        raise ServiceObservationError("SERVICE_CLIENT_CONFIG_INVALID") from None

    identity = _mapping(
        service.get("identity"),
        "SERVICE_IDENTITY_CONFIG_INVALID",
        {"principal_ref", "strategy_ref", "execution_domain_ref"},
    )
    principal_ref = _text(identity["principal_ref"], "SERVICE_PRINCIPAL_REF_INVALID")
    strategy_ref = _text(identity["strategy_ref"], "SERVICE_STRATEGY_REF_INVALID")
    domain_ref = _text(identity["execution_domain_ref"], "SERVICE_DOMAIN_REF_INVALID")
    if public.get("registration", {}).get("strategy_ref") != strategy_ref:
        raise ServiceObservationError("SERVICE_STRATEGY_IDENTITY_MISMATCH")
    clients = public.get("clients", {})
    if set(clients) != {"gateway"}:
        raise ServiceObservationError("SERVICE_CLIENT_SET_UNSUPPORTED")
    bindings = clients["gateway"].get("settings", {}).get("bindings")
    if type(bindings) is not list or len(bindings) != 2:
        raise ServiceObservationError("SERVICE_BINDING_SET_INVALID")
    by_mount = {
        item.get("mount"): item
        for item in bindings
        if isinstance(item, Mapping) and type(item.get("mount")) is str
    }
    if len(by_mount) != 2 or set(by_mount) != {"store.account", "store.market"}:
        raise ServiceObservationError("SERVICE_BINDING_SET_INVALID")

    account = _mapping(service.get("account"), "SERVICE_ACCOUNT_CONFIG_INVALID", _ACCOUNT_FIELDS)
    market = _mapping(service.get("market"), "SERVICE_MARKET_CONFIG_INVALID", _MARKET_FIELDS)
    if account["mount"] != "store.account" or market["mount"] != "store.market":
        raise ServiceObservationError("SERVICE_BINDING_SET_INVALID")
    account_ref = _text(account["account_ref"], "SERVICE_ACCOUNT_REF_INVALID")
    if by_mount["store.account"].get("account_ref") != account_ref:
        raise ServiceObservationError("SERVICE_ACCOUNT_SCOPE_MISMATCH")
    _text(market["source_ref"], "SERVICE_MARKET_SOURCE_REF_INVALID")
    _text(market["entitlement_ref"], "SERVICE_MARKET_ENTITLEMENT_REF_INVALID")

    peers = service.get("service_principals")
    service_ids = {item.get("service_id") for item in bindings}
    if (
        not isinstance(peers, Mapping)
        or set(peers) != service_ids
        or any(type(value) is not str or not value or value != value.strip() for value in peers.values())
    ):
        raise ServiceObservationError("SERVICE_PEER_IDENTITIES_INVALID")

    def scope_resolver(scope_ref: str):
        if scope_ref == by_mount["store.account"].get("scope_ref"):
            return WireScope(domain_ref, account_ref=account_ref, strategy_ref=strategy_ref)
        if scope_ref == by_mount["store.market"].get("scope_ref"):
            return WireScope(domain_ref, strategy_ref=strategy_ref)
        raise ServiceObservationError("SERVICE_SCOPE_REF_UNBOUND")

    def peer_resolver(service_id: str):
        peer = peers.get(service_id)
        if peer is None:
            raise ServiceObservationError("SERVICE_PEER_IDENTITY_UNBOUND")
        return WireIdentity(WireRole.SERVICE, peer, service_id)

    profiles = public.get("communication", {}).get("profiles", {})
    if not isinstance(profiles, Mapping):
        raise ServiceObservationError("SERVICE_TRANSPORT_CONFIG_INVALID")
    references = set()
    for binding in bindings:
        profile = profiles.get(binding.get("transport_ref"))
        if not isinstance(profile, Mapping):
            raise ServiceObservationError("SERVICE_TRANSPORT_CONFIG_INVALID")
        references.add(_text(profile.get("security_profile_ref"), "SERVICE_SECURITY_REF_INVALID"))
    curve_refs = service.get("curve_key_envs")
    if not isinstance(curve_refs, Mapping) or set(curve_refs) != references:
        raise ServiceObservationError("SERVICE_CURVE_REFERENCES_INVALID")
    curve_keys = {}
    for reference in sorted(references):
        env_refs = _mapping(
            curve_refs[reference],
            "SERVICE_CURVE_KEY_REFERENCES_INVALID",
            {"server_key_env", "client_public_key_env", "client_secret_key_env"},
        )
        values = []
        for field in ("server_key_env", "client_public_key_env", "client_secret_key_env"):
            name = _text(env_refs[field], "SERVICE_CURVE_ENV_NAME_INVALID")
            key = env.get(name)
            if type(key) is not str or len(key) != 40 or not key.isascii():
                raise ServiceObservationError("SERVICE_CURVE_KEY_UNAVAILABLE")
            try:
                values.append(key.encode("ascii"))
            except UnicodeEncodeError:
                raise ServiceObservationError("SERVICE_CURVE_KEY_UNAVAILABLE") from None
        curve_keys[reference] = ClientCurveKeys(*values)

    account_operations = (
        _ACCOUNT_OPERATIONS
        if require_instrument_metadata
        else frozenset({"account.snapshot"})
    )
    requested_operations = {
        "store.account": account_operations,
        "store.market": _MARKET_OPERATIONS,
    }
    try:
        runtime = ServiceClientRuntime(
            parsed,
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, principal_ref, strategy_ref),
            scope_resolver=scope_resolver,
            peer_resolver=peer_resolver,
            transport_factory=ZmqTransportFactory(curve_keys),
            requested_operations=requested_operations,
        )
    except Exception:
        raise ServiceObservationError("SERVICE_RUNTIME_CONFIG_INVALID") from None
    return base, runtime, parsed, public, curve_keys, account, market, domain_ref, by_mount


def _account_config(account: Mapping[str, Any], base: Any):
    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    try:
        key_value = account["key"]
        account_key = key_value if type(key_value) is AccountKey else AccountKey.from_dict(key_value)
        raw_coverage = account["required_coverage"]
        if type(raw_coverage) not in {list, tuple} or not raw_coverage:
            raise ValueError
        coverage = tuple(
            item if type(item) is AccountResourceKey else AccountResourceKey.from_dict(item)
            for item in raw_coverage
        )
        if len(set(coverage)) != len(coverage):
            raise ValueError
    except Exception:
        raise ServiceObservationError("SERVICE_ACCOUNT_COVERAGE_INVALID") from None
    return account_key, coverage


def _target_key(instrument: ServiceObservationInstrument, market: Mapping[str, Any], account_key: Any, metadata: Any, base: Any):
    from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
    if instrument.market_key is not None:
        try:
            raw = instrument.market_key
            key = raw if type(raw) is MarketSubscriptionKey else MarketSubscriptionKey.from_dict(raw)
        except Exception:
            raise ServiceObservationError("SERVICE_MARKET_KEY_INVALID") from None
        if (
            key.source_ref != market["source_ref"]
            or key.entitlement_ref != market["entitlement_ref"]
        ):
            raise ServiceObservationError("SERVICE_MARKET_SCOPE_MISMATCH")
        if metadata is not None and (
            key.instrument.instrument_id != metadata.instrument_id
            or key.instrument.venue != metadata.exchange_id
            or key.instrument.product_type != metadata.asset_type
            or key.instrument.environment != account_key.environment
        ):
            raise ServiceObservationError("SERVICE_MARKET_METADATA_MISMATCH")
        return key
    if metadata is None:
        raise ServiceObservationError("SERVICE_CTP_METADATA_REQUIRED")
    try:
        return MarketSubscriptionKey(
            source_ref=market["source_ref"],
            entitlement_ref=market["entitlement_ref"],
            instrument=MarketInstrumentKey(
                provider="ctp",
                venue=metadata.exchange_id,
                environment=account_key.environment,
                product_type=metadata.asset_type,
                instrument_id=metadata.instrument_id,
                native_symbol=metadata.instrument_id,
            ),
            channel="ctp.quote.v2",
        )
    except Exception:
        raise ServiceObservationError("SERVICE_MARKET_KEY_INVALID") from None


class ServiceObservationSession:
    """One owner-thread session; facade close precedes runtime close."""

    def __init__(self, *, runtime: Any, account_client: Any, account_view: Any, metadata: Mapping[str, Any], clients: Mapping[str, Any], proxy: Any, store: Any, bindings: Mapping[str, Any], timeout_seconds: float) -> None:
        self.runtime = runtime
        self.account_client = account_client
        self.account_view = account_view
        self.metadata = MappingProxyType(dict(metadata))
        self.market_clients = MappingProxyType(dict(clients))
        self.proxy = proxy
        self.store = store
        self.bindings = MappingProxyType(dict(bindings))
        self.timeout_seconds = timeout_seconds
        self.cleanup_report: Mapping[str, Any] | None = None
        self._owner_thread = threading.get_ident()
        self._closed = False
        self._started: set[str] = set()
        self._bootstraps: dict[str, Any] = {}

    def __enter__(self) -> ServiceObservationSession:
        self._assert_owner()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise ServiceObservationError("SERVICE_SESSION_WRONG_THREAD")

    def refresh_account(self):
        self._assert_owner()
        if self._closed:
            raise ServiceObservationError("SERVICE_SESSION_CLOSED")
        view = self.account_client.refresh()
        self.account_view = view
        return view

    def subscribe(self, dataname: str):
        self._assert_owner()
        if self._closed:
            raise ServiceObservationError("SERVICE_SESSION_CLOSED")
        client = self.market_clients.get(dataname)
        if client is None:
            raise ServiceObservationError("SERVICE_INSTRUMENT_UNKNOWN")
        if dataname not in self._started:
            if self.proxy is not None and dataname in self.bindings:
                self.proxy.subscribe(dataname)
                descriptor = getattr(client, "source_descriptor", None)
            else:
                bootstrap = client.start()
                if (
                    getattr(client, "healthy", None) is not True
                    or getattr(client, "recovery_required", None) is not False
                    or getattr(bootstrap, "stream_id", None) != client.key.stream_id
                ):
                    raise ServiceObservationError("SERVICE_MARKET_START_UNHEALTHY")
                self._bootstraps[dataname] = bootstrap
                descriptor = getattr(bootstrap, "source_descriptor", None)
                current_descriptor = getattr(client, "source_descriptor", None)
                if descriptor != current_descriptor:
                    raise ServiceObservationError("SERVICE_SOURCE_DESCRIPTOR_CHANGED")
            require_descriptor = self._requires_descriptor(dataname)
            if require_descriptor and descriptor is None:
                raise ServiceObservationError("SERVICE_SOURCE_DESCRIPTOR_UNAVAILABLE")
            if descriptor is not None and (
                descriptor.key != client.key
                or descriptor.stream_id != client.key.stream_id
                or (
                    dataname in self._bootstraps
                    and descriptor.epoch != self._bootstraps[dataname].snapshot_epoch
                )
            ):
                raise ServiceObservationError("SERVICE_SOURCE_DESCRIPTOR_MISMATCH")
            self._started.add(dataname)
        return getattr(client, "source_descriptor", None)

    def initial_snapshot(self, dataname: str):
        """Return the start-time latest-event snapshot, never a full baseline."""

        self._assert_owner()
        bootstrap = self._bootstraps.get(dataname)
        if bootstrap is None:
            return None
        if dataname not in self._started:
            raise ServiceObservationError("SERVICE_MARKET_NOT_STARTED")
        return getattr(bootstrap, "snapshot", None)

    def _requires_descriptor(self, dataname: str) -> bool:
        client = self.market_clients[dataname]
        configured = getattr(client, "_require_source_descriptor", None)
        if type(configured) is bool:
            return configured
        key = client.key
        return key.channel == "ctp.quote.v2"

    def poll(self, dataname: str, *, timeout_ms: int = 0):
        self._assert_owner()
        if self._closed:
            raise ServiceObservationError("SERVICE_SESSION_CLOSED")
        if dataname not in self._started:
            self.subscribe(dataname)
        client = self.market_clients.get(dataname)
        if client is None:
            raise ServiceObservationError("SERVICE_INSTRUMENT_UNKNOWN")
        if self.proxy is not None and dataname in self.bindings:
            binding = self.bindings[dataname]
            if type(binding).__name__ == "ServiceCtpTickBinding":
                return self.proxy.poll_tick(dataname)
            if type(binding).__name__ == "ServiceOrderBookBinding":
                return self.proxy.poll_orderbook(dataname)
        try:
            return client.poll(timeout_ms=timeout_ms)
        except Exception:
            raise ServiceObservationError("SERVICE_MARKET_POLL_FAILED") from None

    def poll_orderbook(self, dataname: str):
        self._assert_owner()
        if self.proxy is None or dataname not in self.bindings:
            raise ServiceObservationError("SERVICE_ORDERBOOK_BINDING_UNAVAILABLE")
        if type(self.bindings[dataname]).__name__ != "ServiceOrderBookBinding":
            raise ServiceObservationError("SERVICE_ORDERBOOK_BINDING_UNAVAILABLE")
        return self.poll(dataname)

    def descriptor(self, dataname: str):
        self._assert_owner()
        if dataname not in self.market_clients:
            raise ServiceObservationError("SERVICE_INSTRUMENT_UNKNOWN")
        return getattr(self.market_clients[dataname], "source_descriptor", None)

    def close(self) -> Mapping[str, Any]:
        self._assert_owner()
        if self.cleanup_report is not None:
            return self.cleanup_report
        if self._closed:
            return MappingProxyType({"status": "PASS", "facades_closed": True, "runtime_closed": True})
        errors: list[str] = []
        facade_state = "PASS"
        if self.store is not None:
            try:
                health = self.store.stop(timeout=self.timeout_seconds)
            except Exception:
                errors.append("store_stop_failed")
                facade_state = "UNCONFIRMED"
            else:
                if not isinstance(health, Mapping) or health.get("shutdown_state") != "PASS":
                    errors.append("store_shutdown_unconfirmed")
                    facade_state = "UNCONFIRMED"
        elif self.proxy is not None:
            try:
                self.proxy.disconnect()
            except Exception:
                errors.append("facade_close_failed")
                facade_state = "UNCONFIRMED"
        else:
            for client in self.market_clients.values():
                try:
                    client.close()
                except Exception:
                    errors.append("market_client_close_failed")
                    facade_state = "UNCONFIRMED"
            try:
                self.account_client.close()
            except Exception:
                errors.append("account_client_close_failed")
                facade_state = "UNCONFIRMED"

        try:
            self.runtime.close()
        except Exception:
            errors.append("runtime_close_failed")
        runtime_state = getattr(self.runtime, "state", None)
        uncertain = (
            facade_state != "PASS"
            or runtime_state != "closed"
            or getattr(self.runtime, "cleanup_failures", 1) != 0
            or getattr(self.runtime, "unregister_uncertainties", 1) != 0
            or getattr(self.runtime, "unknown_registration_count", 1) != 0
            or bool(errors)
        )
        report = MappingProxyType(
            {
                "status": "UNCONFIRMED" if uncertain else "PASS",
                "facades_closed": facade_state == "PASS",
                "runtime_closed": runtime_state == "closed",
                "runtime_cleanup_failures": getattr(self.runtime, "cleanup_failures", None),
                "runtime_unregister_uncertainties": getattr(self.runtime, "unregister_uncertainties", None),
                "runtime_unknown_registrations": getattr(self.runtime, "unknown_registration_count", None),
                "errors": tuple(errors),
            }
        )
        self.cleanup_report = report
        self._closed = not uncertain
        if uncertain:
            refs = (self.runtime, self.account_client, self.proxy, self.store, self.market_clients)
            with _KEEPALIVE_LOCK:
                _CLEANUP_KEEPALIVE.append(refs)
            raise ServiceObservationError("SERVICE_CLEANUP_UNCONFIRMED")
        return report


def _account_observation_projection(session: ServiceObservationSession) -> dict[str, Any]:
    view = session.account_view
    observation = getattr(view, "observation", None)
    if observation is None:
        raise ServiceObservationError("SERVICE_ACCOUNT_SNAPSHOT_UNAVAILABLE")
    required_flags = (
        "balances_complete",
        "positions_complete",
        "open_orders_complete",
    )
    flags = {name: getattr(observation, name, None) for name in required_flags}
    if any(type(value) is not bool for value in flags.values()):
        raise ServiceObservationError("SERVICE_ACCOUNT_COMPLETENESS_INVALID")
    healthy = getattr(session.account_client, "healthy", None) is True
    fresh = type(getattr(view, "fresh_until_monotonic", None)) in (int, float)
    if fresh:
        import time

        fresh = time.monotonic() < view.fresh_until_monotonic
    return {
        "session_generation": getattr(view, "session_generation", None),
        "cursor": getattr(view, "cursor", None),
        "observed_at_utc": getattr(observation, "completed_at_utc", None),
        "consistency": getattr(observation, "consistency", None),
        "balances_complete": flags["balances_complete"],
        "positions_complete": flags["positions_complete"],
        "open_orders_complete": flags["open_orders_complete"],
        "coverage_count": len(getattr(observation, "coverage", ())),
        "balance_count": len(getattr(observation, "balances", ())),
        "position_count": len(getattr(observation, "positions", ())),
        "open_order_count": len(getattr(observation, "open_orders", ()) or ()),
        "facade_healthy": healthy,
        "fresh": fresh,
    }


def _source_descriptor_projection(descriptor: Any, key: Any) -> dict[str, Any]:
    if descriptor is None:
        raise ServiceObservationError("SERVICE_SOURCE_DESCRIPTOR_UNAVAILABLE")
    if (
        getattr(descriptor, "key", None) != key
        or getattr(descriptor, "stream_id", None) != key.stream_id
        or type(getattr(descriptor, "epoch", None)) is not str
        or not descriptor.epoch
    ):
        raise ServiceObservationError("SERVICE_SOURCE_DESCRIPTOR_MISMATCH")
    return {
        "key_matches": True,
        "stream_id": descriptor.stream_id,
        "epoch": descriptor.epoch,
        "provider": descriptor.provider,
        "source": descriptor.source,
        "connection_generation": descriptor.connection_generation,
        "clock_domain_id": descriptor.clock_domain_id,
        "clock_source_session_id": descriptor.clock_source_session_id,
        "clock_source": descriptor.clock_source,
        "clock_mapping_qualified": False,
        "freshness_qualified": False,
        "execution_eligible": False,
    }


def _market_event_projection(event: Any, *, origin: str) -> dict[str, Any] | None:
    if event is None:
        return None
    header = getattr(event, "header", None)
    if header is not None:
        return {
            "origin": origin,
            "operation": getattr(header, "operation", None),
            "schema_id": getattr(header, "schema_id", None),
            "stream_id": getattr(header, "stream_id", None),
            "stream_epoch": getattr(header, "stream_epoch", None),
            "sequence": getattr(header, "sequence", None),
            "sent_at_utc": getattr(header, "sent_at_utc", None),
            "payload_present": bool(getattr(event, "payload", None)),
        }
    return {
        "origin": origin,
        "event_type": type(event).__name__,
        "sequence": getattr(event, "sequence", None),
        "symbol": getattr(event, "symbol", None),
        "payload_present": True,
    }


def _poll_until_event(session: ServiceObservationSession, dataname: str, timeout_ms: int):
    """Poll through bounded empty reads instead of treating one as the deadline."""

    deadline = monotonic() + timeout_ms / 1000.0
    while True:
        remaining = max(0.0, deadline - monotonic())
        remaining_ms = min(timeout_ms, int(remaining * 1000))
        event = session.poll(dataname, timeout_ms=remaining_ms)
        if event is not None or remaining_ms == 0:
            return event
        # SDK polling can return early at a head/maintenance boundary. Avoid
        # a busy loop while preserving the caller's single bounded deadline.
        sleep(min(0.01, max(0.0, deadline - monotonic())))


def collect_service_observation(
    service_config: Mapping[str, Any],
    *,
    instruments: tuple[ServiceObservationInstrument, ...] | list[ServiceObservationInstrument],
    timeout_ms: int = 2000,
    environ: Mapping[str, str] | None = None,
    sdk_root: str | os.PathLike[str] | None = None,
) -> Mapping[str, Any]:
    """Read one account view and one bounded market event per named instrument.

    This path never creates a Store, Broker, Cerebro or order-capable client.
    Market source identity is reported separately from clock qualification.
    """

    if type(timeout_ms) is not int or not 0 <= timeout_ms <= 30_000:
        raise ServiceObservationError("SERVICE_POLL_TIMEOUT_INVALID")
    session = open_service_read_session(
        service_config,
        instruments=instruments,
        allow_write=False,
        environ=environ,
        sdk_root=sdk_root,
    )
    read_error: ServiceObservationError | None = None
    cleanup: Mapping[str, Any] | None = None
    report: dict[str, Any] = {}
    try:
        account = _account_observation_projection(session)
        rows: list[dict[str, Any]] = []
        for instrument in instruments:
            descriptor = session.subscribe(instrument.dataname)
            key = session.market_clients[instrument.dataname].key
            source = _source_descriptor_projection(descriptor, key)
            event = _poll_until_event(session, instrument.dataname, timeout_ms)
            origin = "poll"
            if event is None:
                event = session.initial_snapshot(instrument.dataname)
                origin = "bootstrap_latest_event"
            event_projection = _market_event_projection(event, origin=origin)
            metadata = session.metadata.get(instrument.dataname)
            metadata_projection = None
            if metadata is not None:
                metadata_projection = {
                    "instrument_id": metadata.instrument_id,
                    "exchange_id": metadata.exchange_id,
                    "product_class": metadata.product_class,
                    "asset_type": metadata.asset_type,
                    "price_tick": metadata.price_tick,
                    "volume_multiple": metadata.volume_multiple,
                    "price_limits_available": metadata.price_limits_available,
                    "price_limits_source": metadata.price_limits_source,
                    "observed_at_utc": metadata.observed_at_utc,
                    "source_revision": metadata.source_revision,
                    "source": metadata.source,
                }
            rows.append(
                {
                    "dataname": instrument.dataname,
                    "instrument_id": instrument.instrument_id,
                    "exchange_id": instrument.exchange_id,
                    "metadata": metadata_projection,
                    "source": source,
                    "latest_event": event_projection,
                }
            )
        report = {
            "status": "OBSERVED"
            if account["facade_healthy"]
            and account["fresh"]
            and account["balances_complete"]
            and account["positions_complete"]
            and account["open_orders_complete"]
            and all(row["latest_event"] is not None for row in rows)
            else "BLOCKED",
            "observation_level": "SERVICE_READ_ONLY_LOCAL_ENTRY",
            "write_capability": "UNSUPPORTED",
            "account_snapshot": account,
            "instruments": rows,
        }
    except ServiceObservationError as error:
        read_error = error
    finally:
        try:
            cleanup = session.close()
        except ServiceObservationError as error:
            cleanup_error = error
        else:
            cleanup_error = None
    if cleanup_error is not None:
        raise cleanup_error
    if read_error is not None:
        raise read_error
    assert cleanup is not None
    report["cleanup"] = dict(cleanup)
    if cleanup.get("status") != "PASS":
        report["status"] = "BLOCKED"
    return MappingProxyType(report)


def observe_service_contracts(
    service_config_path: str | os.PathLike[str],
    contracts: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    *,
    timeout_ms: int = 2000,
    environ: Mapping[str, str] | None = None,
    sdk_root: str | os.PathLike[str] | None = None,
) -> Mapping[str, Any]:
    """Run a read-only observation for case-owned ``(instrument, exchange)`` pairs."""

    if type(contracts) not in (tuple, list) or not contracts:
        raise ServiceObservationError("SERVICE_CONTRACTS_INVALID")
    instruments: list[ServiceObservationInstrument] = []
    seen: set[tuple[str, str]] = set()
    for pair in contracts:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ServiceObservationError("SERVICE_CONTRACTS_INVALID")
        instrument_id = _text(pair[0], "SERVICE_INSTRUMENT_ID_INVALID")
        exchange_id = _text(pair[1], "SERVICE_EXCHANGE_ID_INVALID")
        identity = (exchange_id, instrument_id)
        if identity in seen:
            raise ServiceObservationError("SERVICE_INSTRUMENT_DUPLICATE")
        seen.add(identity)
        instruments.append(
            ServiceObservationInstrument(
                dataname=f"{exchange_id}.{instrument_id}",
                instrument_id=instrument_id,
                exchange_id=exchange_id,
            )
        )
    service_config = load_service_observation_config(service_config_path)
    return collect_service_observation(
        service_config,
        instruments=instruments,
        timeout_ms=timeout_ms,
        environ=environ,
        sdk_root=sdk_root,
    )


def open_service_read_session(
    service_config: Mapping[str, Any],
    *,
    instruments: tuple[ServiceObservationInstrument, ...] | list[ServiceObservationInstrument],
    allow_write: bool = False,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    sdk_root: str | os.PathLike[str] | None = None,
) -> ServiceObservationSession:
    """Start a bounded read-only SDK session; this function never creates a Host.

    ``allow_write`` is refused before reading config values, environment names,
    loading the SDK, or creating a client runtime.  The account resource and
    market key identities come from explicit caller fields only.
    """

    if allow_write is not False:
        raise ServiceObservationError("SERVICE_OBSERVATION_WRITE_UNSUPPORTED")
    if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0 or timeout_seconds > 300:
        raise ServiceObservationError("SERVICE_TIMEOUT_INVALID")
    if type(instruments) not in (tuple, list) or not instruments:
        raise ServiceObservationError("SERVICE_INSTRUMENTS_INVALID")
    if any(type(item) is not ServiceObservationInstrument for item in instruments):
        raise ServiceObservationError("SERVICE_INSTRUMENTS_INVALID")
    names = [item.dataname for item in instruments]
    if len(set(names)) != len(names):
        raise ServiceObservationError("SERVICE_INSTRUMENT_DUPLICATE")
    service = _mapping(service_config, "SERVICE_CONFIG_INVALID", _SERVICE_FIELDS)
    env = os.environ if environ is None else environ
    if not isinstance(env, Mapping):
        raise ServiceObservationError("SERVICE_ENVIRONMENT_INVALID")

    root = _source_roots(sdk_root)
    base, runtime, parsed, public, curve_keys, account_spec, market_spec, domain_ref, bindings_by_mount = (
        _build_runtime(
            service,
            env,
            root,
            require_instrument_metadata=any(item.instrument_id is not None for item in instruments),
        )
    )
    account_client = None
    clients: dict[str, Any] = {}
    proxy = None
    store = None
    try:
        account_key, coverage = _account_config(account_spec, base)

        from bt_api_py.service_account import ServiceAccountClient, ServiceAccountInstrumentMetadata
        from bt_api_py.service_market import ServiceMarketClient, ZmqMarketTransportFactory
        from bt_api_base.service_protocol import WireScope

        market_factory = ZmqMarketTransportFactory(curve_keys)
        runtime.start()
        if runtime.healthy is not True:
            raise ServiceObservationError("SERVICE_RUNTIME_NOT_HEALTHY")
        account_client = ServiceAccountClient(
            runtime,
            account_spec["mount"],
            account_ref=account_spec["account_ref"],
            expected_account=account_key,
            required_coverage=coverage,
            require_open_orders=True,
        )
        account_view = account_client.refresh()
        if account_view.observation.account_key != account_key:
            raise ServiceObservationError("SERVICE_ACCOUNT_IDENTITY_MISMATCH")
        metadata: dict[str, Any] = {}
        clients: dict[str, Any] = {}
        keys: dict[str, Any] = {}
        for item in instruments:
            typed_metadata = None
            if item.instrument_id is not None:
                try:
                    typed_metadata = account_client.instrument_metadata(item.instrument_id, item.exchange_id)
                except Exception:
                    raise ServiceObservationError("SERVICE_INSTRUMENT_METADATA_READ_FAILED") from None
                if type(typed_metadata) is not ServiceAccountInstrumentMetadata:
                    raise ServiceObservationError("SERVICE_INSTRUMENT_METADATA_TYPE_INVALID")
                if (
                    typed_metadata.instrument_id != item.instrument_id
                    or typed_metadata.exchange_id != item.exchange_id
                    or typed_metadata.account_session_generation != account_view.session_generation
                    or typed_metadata.quote_source != "ctp.native.md"
                ):
                    raise ServiceObservationError("SERVICE_INSTRUMENT_METADATA_IDENTITY_MISMATCH")
                metadata[item.dataname] = typed_metadata
            key = _target_key(item, market_spec, account_key, typed_metadata, base)
            resource = None
            if item.resource is not None:
                from bt_api_base.account_protocol import AccountResourceKey

                resource = (
                    item.resource
                    if type(item.resource) is AccountResourceKey
                    else AccountResourceKey.from_dict(item.resource)
                )
                if resource not in coverage:
                    raise ServiceObservationError("SERVICE_RESOURCE_OUTSIDE_COVERAGE")
                if resource.product_type != key.instrument.product_type:
                    raise ServiceObservationError("SERVICE_RESOURCE_PRODUCT_MISMATCH")
            if item.require_source_descriptor is None:
                require_descriptor = key.channel in {"ctp.quote.v2", "orderbook"}
            else:
                require_descriptor = item.require_source_descriptor
            client = ServiceMarketClient(
                runtime,
                market_spec["mount"],
                key,
                subscriber_factory=market_factory,
                stream_scope=WireScope(domain_ref),
                require_source_descriptor=require_descriptor,
            )
            clients[item.dataname] = client
            keys[item.dataname] = key
        bindings: dict[str, Any] = {}
        if any(item.resource is not None for item in instruments):
            if not all(item.resource is not None for item in instruments):
                raise ServiceObservationError("SERVICE_FEED_RESOURCE_SET_INCOMPLETE")
            from backtrader.stores.service_read_proxy import (
                ServiceCtpTickBinding,
                ServiceFeedBinding,
                ServiceReadProxy,
            )

            try:
                for item in instruments:
                    key = keys[item.dataname]
                    from bt_api_base.account_protocol import AccountResourceKey

                    resource = (
                        item.resource
                        if type(item.resource) is AccountResourceKey
                        else AccountResourceKey.from_dict(item.resource)
                    )
                    if key.channel == "ctp.quote.v2":
                        if item.dataname not in metadata or item.qty_unit is None:
                            raise ServiceObservationError("SERVICE_CTP_FEED_BINDING_INVALID")
                        bindings[item.dataname] = ServiceCtpTickBinding(
                            market_client=clients[item.dataname],
                            resource=resource,
                            qty_unit=item.qty_unit,
                            account_session_generation=account_view.session_generation,
                            quantity_multiplier=item.quantity_multiplier,
                        )
                    elif key.channel == "bar":
                        if item.qty_unit is None:
                            raise ServiceObservationError("SERVICE_BAR_FEED_BINDING_INVALID")
                        timeframe = key.timeframe
                        if type(timeframe) is not str:
                            raise ServiceObservationError("SERVICE_BAR_FEED_BINDING_INVALID")
                        bindings[item.dataname] = ServiceFeedBinding(
                            market_client=clients[item.dataname],
                            resource=resource,
                            qty_unit=item.qty_unit,
                            timeframe=timeframe,
                            quantity_multiplier=item.quantity_multiplier,
                        )
                    elif key.channel == "orderbook":
                        try:
                            from backtrader.stores.service_read_proxy import ServiceOrderBookBinding
                        except ImportError:
                            raise ServiceObservationError("SERVICE_ORDERBOOK_BINDING_UNAVAILABLE") from None
                        if item.qty_unit is None:
                            raise ServiceObservationError("SERVICE_ORDERBOOK_BINDING_INVALID")
                        bindings[item.dataname] = ServiceOrderBookBinding(
                            market_client=clients[item.dataname],
                            resource=resource,
                            qty_unit=item.qty_unit,
                            quantity_multiplier=item.quantity_multiplier,
                            max_depth=key.depth,
                            max_event_age_seconds=item.max_event_age_seconds,
                        )
                    else:
                        raise ServiceObservationError("SERVICE_MARKET_CHANNEL_UNSUPPORTED")
                account_cfg = account_spec
                proxy = ServiceReadProxy(
                    account_client,
                    bindings,
                    valuation_currency=_text(
                        account_cfg["valuation_currency"], "SERVICE_VALUATION_CURRENCY_INVALID"
                    ),
                    position_mode=_text(account_cfg["position_mode"], "SERVICE_POSITION_MODE_INVALID"),
                )
                from backtrader.stores.btapistore import BtApiStore

                store = BtApiStore(api=proxy)
                proxy.connect()
                account_view = account_client.snapshot()
            except ServiceObservationError:
                raise
            except Exception:
                raise ServiceObservationError("SERVICE_READ_PROXY_CONFIG_INVALID") from None
        else:
            proxy = None
            store = None
        return ServiceObservationSession(
            runtime=runtime,
            account_client=account_client,
            account_view=account_view,
            metadata=metadata,
            clients=clients,
            proxy=proxy,
            store=store,
            bindings=bindings,
            timeout_seconds=float(timeout_seconds),
        )
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        partial_cleanup_failed = False
        if store is not None:
            try:
                health = store.stop(timeout=float(timeout_seconds))
                partial_cleanup_failed = not (
                    isinstance(health, Mapping) and health.get("shutdown_state") == "PASS"
                )
            except Exception:
                partial_cleanup_failed = True
        elif proxy is not None:
            try:
                proxy.disconnect()
            except Exception:
                partial_cleanup_failed = True
        else:
            for client in clients.values():
                try:
                    client.close()
                except Exception:
                    partial_cleanup_failed = True
            if account_client is not None:
                try:
                    account_client.close()
                except Exception:
                    partial_cleanup_failed = True
        try:
            runtime.close()
        except Exception:
            partial_cleanup_failed = True
        partial_cleanup_failed = partial_cleanup_failed or (
            getattr(runtime, "state", None) != "closed"
            or getattr(runtime, "cleanup_failures", 1) != 0
            or getattr(runtime, "unregister_uncertainties", 1) != 0
            or getattr(runtime, "unknown_registration_count", 1) != 0
        )
        if partial_cleanup_failed:
            with _KEEPALIVE_LOCK:
                _CLEANUP_KEEPALIVE.append((runtime, account_client, proxy, store, clients))
        if isinstance(error, ServiceObservationError):
            raise
        raise ServiceObservationError("SERVICE_SESSION_START_FAILED") from None

