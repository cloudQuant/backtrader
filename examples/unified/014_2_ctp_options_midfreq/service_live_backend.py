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

import copy
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
_ACCOUNT_OPERATIONS = frozenset(
    {"account.snapshot", "account.instrument_metadata"}
)
_MARKET_OPERATIONS = frozenset(
    {
        "market.subscribe",
        "market.unsubscribe",
        "market.snapshot",
        "market.head",
        "market.read_after",
    }
)
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
    from bt_api_base.account_protocol import AccountKey, AccountResourceKey

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


def _curve_profiles(service: Mapping[str, Any], client_public: Mapping[str, Any], env: Mapping[str, str]):
    from bt_api_py.service_runtime import ClientCurveKeys

    profiles = client_public.get("communication", {}).get("profiles", {})
    if not isinstance(profiles, Mapping):
        raise ServiceBackendError("SERVICE_TRANSPORT_CONFIG_INVALID")
    bindings = client_public.get("clients", {}).get("gateway", {}).get("settings", {}).get("bindings")
    if type(bindings) is not list or len(bindings) != 2:
        raise ServiceBackendError("SERVICE_BINDING_SET_INVALID")
    refs: set[str] = set()
    for binding in bindings:
        transport_ref = binding.get("transport_ref") if isinstance(binding, Mapping) else None
        profile = client_public.get("communication", {}).get("profiles", {}).get(transport_ref)
        if not isinstance(profile, Mapping):
            raise ServiceBackendError("SERVICE_TRANSPORT_CONFIG_INVALID")
        refs.add(_text(profile.get("security_profile_ref"), "security_profile_ref"))
    raw_envs = service.get("curve_key_envs")
    if not isinstance(raw_envs, Mapping) or set(raw_envs) != refs:
        raise ServiceBackendError("SERVICE_CURVE_REFERENCES_INVALID")
    result = {}
    for reference in sorted(refs):
        key_refs = _mapping(
            raw_envs[reference],
            "curve_key_env",
            {"server_key_env", "client_public_key_env", "client_secret_key_env"},
        )
        values = []
        for field in ("server_key_env", "client_public_key_env", "client_secret_key_env"):
            env_name = _text(key_refs[field], field)
            value = env.get(env_name)
            if type(value) is not str or len(value) != 40 or not value.isascii():
                raise ServiceBackendError("SERVICE_CURVE_KEY_UNAVAILABLE")
            try:
                values.append(value.encode("ascii"))
            except UnicodeEncodeError:
                raise ServiceBackendError("SERVICE_CURVE_KEY_UNAVAILABLE") from None
        result[reference] = ClientCurveKeys(*values)
    return result


def _runtime_from_config(service: Mapping[str, Any], env: Mapping[str, str]):
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import ServiceClientRuntime, ZmqTransportFactory

    try:
        parsed = parse_client_config(copy.deepcopy(service["client_config"]))
        public = parsed.to_public_dict()
    except Exception:
        raise ServiceBackendError("SERVICE_CLIENT_CONFIG_INVALID") from None
    identity_raw = _mapping(
        service["identity"],
        "identity",
        {"principal_ref", "strategy_ref", "execution_domain_ref"},
    )
    principal_ref = _text(identity_raw["principal_ref"], "principal_ref")
    strategy_ref = _text(identity_raw["strategy_ref"], "strategy_ref")
    domain_ref = _text(identity_raw["execution_domain_ref"], "execution_domain_ref")
    registration = public.get("registration", {})
    if registration.get("strategy_ref") != strategy_ref:
        raise ServiceBackendError("SERVICE_STRATEGY_IDENTITY_MISMATCH")
    clients = public.get("clients", {})
    if set(clients) != {"gateway"}:
        raise ServiceBackendError("SERVICE_CLIENT_SET_INVALID")
    gateway = clients["gateway"]
    if len(gateway.get("settings", {}).get("bindings", ())) != 2:
        raise ServiceBackendError("SERVICE_BINDING_SET_INVALID")
    bindings = gateway["settings"]["bindings"]
    by_mount = {item.get("mount"): item for item in bindings if isinstance(item, Mapping)}
    if len(by_mount) != 2 or set(by_mount) != {"store.account", "store.market"}:
        raise ServiceBackendError("SERVICE_BINDING_SET_INVALID")
    account_spec = service.get("account")
    market_spec = service.get("market")
    if not isinstance(account_spec, Mapping) or not isinstance(market_spec, Mapping):
        raise ServiceBackendError("SERVICE_CONFIG_INVALID")
    account = _mapping(
        account_spec,
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
    market = _mapping(
        market_spec,
        "market",
        {"mount", "source_ref", "entitlement_ref"},
    )
    if account["mount"] != "store.account" or market["mount"] != "store.market":
        raise ServiceBackendError("SERVICE_BINDING_SET_INVALID")
    if by_mount["store.account"].get("account_ref") != account["account_ref"]:
        raise ServiceBackendError("SERVICE_ACCOUNT_SCOPE_MISMATCH")
    peers = service.get("service_principals")
    expected_services = {item.get("service_id") for item in bindings}
    if (
        not isinstance(peers, Mapping)
        or set(peers) != expected_services
        or any(type(value) is not str or not value or value != value.strip() for value in peers.values())
    ):
        raise ServiceBackendError("SERVICE_PEER_IDENTITIES_INVALID")

    def scope_resolver(scope_ref: str):
        if scope_ref == by_mount["store.account"].get("scope_ref"):
            return WireScope(domain_ref, account_ref=account["account_ref"], strategy_ref=strategy_ref)
        if scope_ref == by_mount["store.market"].get("scope_ref"):
            return WireScope(domain_ref, strategy_ref=strategy_ref)
        raise ServiceBackendError("SERVICE_SCOPE_REF_UNBOUND")

    def peer_resolver(service_id: str):
        principal = peers.get(service_id)
        if principal is None:
            raise ServiceBackendError("SERVICE_PEER_IDENTITY_UNBOUND")
        return WireIdentity(WireRole.SERVICE, principal, service_id)

    keys = _curve_profiles(service, public, env)
    try:
        runtime = ServiceClientRuntime(
            parsed,
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, principal_ref, strategy_ref),
            scope_resolver=scope_resolver,
            peer_resolver=peer_resolver,
            transport_factory=ZmqTransportFactory(keys),
            requested_operations={
                "store.account": _ACCOUNT_OPERATIONS,
                "store.market": _MARKET_OPERATIONS,
            },
        )
    except Exception:
        raise ServiceBackendError("SERVICE_RUNTIME_CONFIG_INVALID") from None
    return runtime, public, keys, account, market, domain_ref


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
    from bt_api_py.service_account import ServiceAccountInstrumentMetadata

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
        if type(item) is not ServiceAccountInstrumentMetadata:
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
    from bt_api_base.market_protocol import MarketSourceDescriptor

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
        root / "bt_api" / "bt_api_ctp" / "src",
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
    import bt_api_ctp
    import bt_api_py
    import bt_api_transport_zmq

    for module in (bt_api_base, bt_api_ctp, bt_api_py, bt_api_transport_zmq):
        _require_dev_origin(module, root)
    return bt_api_base, bt_api_ctp, bt_api_py, bt_api_transport_zmq


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
        encoding="utf-8",
    )


def run_live_service(args: Any, raw_config: Mapping[str, Any], decision: Any, runner_module: Any) -> int:
    """Run the normal CTP read-only service path; never fall back to direct."""
    decision_evidence = decision.as_evidence() if decision is not None else {}
    if getattr(args, "allow_write", False):
        runner_module._json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": "write_tier_not_implemented_for_decision_only_strategy",
                "write_grant_result": "refused_no_order_path_by_contract",
                "entry_tier": dict(decision_evidence),
            }
        )
        return EXIT_BLOCKED
    if os.sys.version_info[:2] != (3, 11):
        runner_module._json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": "live_tier_requires_python_3_11",
                "current": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
            }
        )
        return EXIT_BLOCKED

    service = None
    try:
        live = raw_config.get("live_adapter")
        if not isinstance(live, Mapping):
            raise ServiceBackendError("SERVICE_LIVE_ADAPTER_INVALID")
        service = _service_document(live)
        account_spec = _mapping(
            service.get("account"),
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
        market_spec = _mapping(
            service.get("market"),
            "market",
            {"mount", "source_ref", "entitlement_ref"},
        )
        service_root = _source_roots()
        _load_service_dependencies(service_root)
        account_key, coverage, resources = _account_resources(service["account"])
        legacy = runner_module._load_legacy()
        legacy_config = legacy.load_config()
        live_candidate = dict(live.get("live_candidate") or {})
        strategy_ref = str(service["identity"].get("strategy_ref") or "")
        if strategy_ref != runner_module.STRATEGY_ID:
            raise ServiceBackendError("SERVICE_STRATEGY_IDENTITY_MISMATCH")
        contracts = dict(live_candidate.get("contracts") or {})
        if set(contracts) != set(_LEG_NAMES) or any(type(contracts[name]) is not str for name in _LEG_NAMES):
            raise ServiceBackendError("SERVICE_CONTRACT_SET_INVALID")
        if account_spec.get("position_mode") not in {"net", "dual_side"}:
            raise ServiceBackendError("SERVICE_POSITION_MODE_INVALID")
        if account_spec.get("qty_unit") != "contracts":
            raise ServiceBackendError("SERVICE_QUANTITY_UNIT_INVALID")
        valuation_currency = _text(account_spec.get("valuation_currency"), "valuation_currency")
        _text(market_spec.get("source_ref"), "source_ref")
        _text(market_spec.get("entitlement_ref"), "entitlement_ref")

        # Constructing a runtime is still side-effect free.  Defer even that
        # object until all local strategy/account config checks have passed;
        # the first transport opens only at runtime.start() below.

        from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
        from bt_api_base.service_protocol import WireScope
        from bt_api_py.service_account import ServiceAccountClient
        from bt_api_py.service_market import ServiceMarketClient, ZmqMarketTransportFactory
        from backtrader.stores.btapistore import BtApiStore
        from backtrader.stores.service_read_proxy import ServiceCtpTickBinding, ServiceReadProxy
        import backtrader as bt

        timeout_config = dict(live.get("timeouts") or {})
        run_seconds = float(getattr(args, "run_seconds", None) or timeout_config.get("run_seconds") or 60.0)
        if not math.isfinite(run_seconds) or run_seconds <= 0:
            raise ServiceBackendError("SERVICE_RUN_WINDOW_INVALID")
        run_seconds = min(run_seconds, 7200.0)
        run_id = (
            f"live-service-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        output_directory = Path(args.evidence_dir) if args.evidence_dir else (
            Path(runner_module.HERE) / "evidence" / run_id
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "example_id": "014_2_ctp_options_midfreq",
            "mode": "live",
            "backend": "service",
            "tier": "observation_only_feed_sealed",
            "entry_tier": dict(decision_evidence),
            "write_grant_result": "refused_no_order_path_by_contract",
            "status": "STARTING",
            "evidence_directory": str(output_directory),
            "service_clock_qualification": "NOT_QUALIFIED",
            "service_clock_reason": "ctp_receive_clock_mapping_unavailable",
            "source_identity_is_clock_qualification": False,
            "external_request_counts": {"order_write": 0},
        }
        _write_json(output_directory / "run.json", summary)

        account_client = None
        market_clients: list[Any] = []
        proxy = None
        store = None
        broker = None
        cerebro = None
        runtime = None
        curve_keys = {}
        result_code = EXIT_BLOCKED
        started_mono = time.monotonic()
        strategy_view = None
        strategy_instance = None
        run_exception = None
        cleanup_errors: list[str] = []
        try:
            runtime, _client_public, curve_keys, _account, _market, domain_ref = (
                _runtime_from_config(service, os.environ)
            )
            runtime.start()
            if runtime.healthy is not True:
                raise ServiceBackendError("SERVICE_RUNTIME_NOT_HEALTHY")
            account_client = ServiceAccountClient(
                runtime,
                account_spec["mount"],
                account_ref=account_spec["account_ref"],
                expected_account=account_key,
                required_coverage=coverage,
                require_open_orders=True,
            )
            initial_view = account_client.refresh()
            first_observation = initial_view.observation
            if first_observation.account_key != account_key:
                raise ServiceBackendError("SERVICE_ACCOUNT_IDENTITY_MISMATCH")
            metadata = _metadata_set(account_client, initial_view, contracts)
            _validate_candidate_multiplier(
                live_candidate,
                metadata,
                fallback_candidate=legacy_config.get("candidate"),
            )
            by_leg_resources = resources
            feeds: dict[str, Any] = {}
            market_factory = ZmqMarketTransportFactory(curve_keys)
            metadata_projection = {}
            for leg in _LEG_NAMES:
                item = metadata[leg]
                full_symbol = contracts[leg]
                exchange, _, instrument_id = full_symbol.partition(".")
                resource = by_leg_resources[leg]
                if resource.product_type != item.asset_type:
                    raise ServiceBackendError("SERVICE_RESOURCE_PRODUCT_MISMATCH")
                key = MarketSubscriptionKey(
                    source_ref=market_spec["source_ref"],
                    entitlement_ref=market_spec["entitlement_ref"],
                    instrument=MarketInstrumentKey(
                        provider="ctp",
                        venue=item.exchange_id,
                        environment=account_key.environment,
                        product_type=item.asset_type,
                        instrument_id=item.instrument_id,
                        native_symbol=item.instrument_id,
                    ),
                    channel="ctp.quote.v2",
                )
                client = ServiceMarketClient(
                    runtime,
                    market_spec["mount"],
                    key,
                    subscriber_factory=market_factory,
                    stream_scope=WireScope(domain_ref),
                    require_source_descriptor=True,
                )
                market_clients.append(client)
                feeds[instrument_id] = ServiceCtpTickBinding(
                    market_client=client,
                    resource=resource,
                    qty_unit=account_spec["qty_unit"],
                    account_session_generation=initial_view.session_generation,
                    quantity_multiplier="1",
                )
                metadata_projection[leg] = {
                    "symbol": full_symbol,
                    "instrument_id": item.instrument_id,
                    "exchange_id": item.exchange_id,
                    "asset_type": item.asset_type,
                    "price_tick": item.price_tick,
                    "volume_multiple": item.volume_multiple,
                    "price_limits_available": item.price_limits_available,
                    "price_limits_source": item.price_limits_source,
                    "account_session_generation": item.account_session_generation,
                    "trader_connection_generation": item.source_connection_generation,
                }

            proxy = ServiceReadProxy(
                account_client,
                feeds,
                valuation_currency=valuation_currency,
                position_mode=account_spec["position_mode"],
            )
            # Start each exact ServiceMarket subscription through the normal
            # typed client and proxy before creating Cerebro's strategy. This
            # makes the actual authenticated descriptor available to the
            # strategy's existing shared-clock barrier. BtApiStore/Feed later
            # call these same idempotent start/subscribe entry points.
            proxy.connect()
            market_source_descriptors = {}
            for leg in _LEG_NAMES:
                instrument_id = metadata[leg].instrument_id
                proxy.subscribe(instrument_id)
                market_source_descriptors[leg] = proxy.ctp_tick_source_descriptor(
                    instrument_id
                )
            market_clock_domain = _validate_shared_market_source_descriptors(
                market_source_descriptors
            )
            for leg, descriptor in market_source_descriptors.items():
                metadata_projection[leg]["market_source_descriptor"] = {
                    "key": descriptor.key.to_dict(),
                    "stream_id": descriptor.stream_id,
                    "epoch": descriptor.epoch,
                    "provider": descriptor.provider,
                    "source": descriptor.source,
                    "connection_generation": descriptor.connection_generation,
                    "clock_domain_id": descriptor.clock_domain_id,
                    "clock_source_session_id": descriptor.clock_source_session_id,
                    "clock_source": descriptor.clock_source,
                    "clock_qualification": "NOT_QUALIFIED",
                }
            store = BtApiStore(api=proxy)
            broker = store.getbroker(
                market_data_only=True,
                position_mode=account_spec["position_mode"],
                max_order_size=1,
                cash_check_enabled=True,
                sdk_preflight=False,
                require_complete_ctp_evidence=False,
                force_refresh_queries=False,
                position_sync_policy="startup",
                account_refresh_interval=3600.0,
                open_orders_refresh_interval=3600.0,
                flatten_on_stop=False,
                shutdown_timeout=float(timeout_config.get("stop_seconds") or 10.0),
            )
            contracts_payload = {name: contracts[name] for name in _LEG_NAMES}
            rules_payload = {
                "strategy": runner_module.STRATEGY_ID,
                "candidate": runner_module.LIVE_CANDIDATE_ID,
                "contracts": contracts_payload,
                "provider_metadata": {
                    name: {
                        "source": metadata[name].source,
                        "source_revision": metadata[name].source_revision,
                        "source_records_sha256": metadata[name].source_records_sha256,
                        "price_tick": metadata[name].price_tick,
                        "volume_multiple": metadata[name].volume_multiple,
                    }
                    for name in _LEG_NAMES
                },
            }
            rules_hash = hashlib.sha256(
                json.dumps(
                    rules_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            strategy_view = runner_module._live_strategy_config(
                legacy_config, live, rules_hash
            )
            strategy_view["candidate"]["price_ticks"] = {
                name: float(_positive_decimal(metadata[name].price_tick))
                for name in _LEG_NAMES
            }
            summary.update(
                {
                    "service_session": {
                        "runtime_state": runtime.state,
                        "account_session_generation_present": bool(initial_view.session_generation),
                        "account_snapshot_id_present": bool(initial_view.snapshot_id),
                        "account_coverage_count": len(first_observation.coverage),
                        "position_rows": len(first_observation.positions),
                        "open_order_rows": len(first_observation.open_orders or ()),
                        "metadata": metadata_projection,
                    },
                    "strategy": {
                        "strategy_id": runner_module.STRATEGY_ID,
                        "candidate_id": runner_module.LIVE_CANDIDATE_ID,
                        "contracts": contracts_payload,
                        "rules_hash": rules_hash,
                    },
                    "provider_operations": {
                        "account_snapshot": "COMPLETE",
                        "instrument_metadata": 3,
                        "market_subscriptions": len(market_clients),
                    },
                    "live_window_seconds": run_seconds,
                }
            )
            cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
            cerebro.setbroker(broker)
            for leg in _LEG_NAMES:
                full_symbol = contracts[leg]
                _, _, instrument_id = full_symbol.partition(".")
                feed = store.getdata(
                    dataname=instrument_id,
                    timeframe=bt.TimeFrame.Minutes,
                    compression=1,
                    dispatch_bars=True,
                    dispatch_ticks=False,
                    backfill_start=False,
                    qcheck=0.1,
                    closed_bar_quote_capture=True,
                    closed_bar_quote_limit=int(
                        (live.get("observation") or {}).get("quote_limit") or 240
                    ),
                )
                cerebro.adddata(feed, name=full_symbol)
            strategy_module = __import__("ctp_options_midfreq_strategy")
            strategy_cls = strategy_module.CTPOptionsMidFrequencyStrategy
            try:
                Path(strategy_module.__file__).resolve().relative_to(Path(runner_module.HERE).resolve())
            except (OSError, ValueError):
                raise ServiceBackendError("SERVICE_STRATEGY_ORIGIN_NOT_EXAMPLE") from None
            strategy_view["candidate"]["exchange"] = str(
                live["live_candidate"].get("exchange") or ""
            )
            cerebro.addstrategy(
                strategy_cls,
                config=strategy_view,
                quote_producer=None,
                timing_provider=None,
                require_feed_bar_evidence=True,
                feed_evidence_clock_mode="live",
                # This is the identity observed from the active market
                # subscriptions. It does not qualify a clock mapping; no
                # decision is accepted until run-owned clock proof exists.
                feed_evidence_clock_domain=market_clock_domain,
                max_pending_feed_decisions=int(
                    (live.get("observation") or {}).get("max_pending_decisions") or 8
                ),
            )
            stop_event = threading.Event()

            def _stop_window() -> None:
                if not stop_event.wait(run_seconds):
                    cerebro.runstop()

            stopper = threading.Thread(
                target=_stop_window, name="0142-service-window-stop", daemon=True
            )
            stopper.start()
            summary["status"] = "RUNNING"
            _write_json(output_directory / "run.json", summary)
            try:
                run_results = cerebro.run()
                if run_results and run_results[0]:
                    strategy_instance = run_results[0][0]
            except Exception as exc:
                run_exception = type(exc).__name__
            finally:
                stop_event.set()
                stopper.join(timeout=2.0)
            if stopper.is_alive():
                run_exception = run_exception or "StopperJoinUnconfirmed"
            report = {}
            if strategy_instance is not None:
                build_report = getattr(strategy_instance, "build_report", None) or getattr(
                    strategy_instance, "report", None
                )
                if callable(build_report):
                    try:
                        report = build_report() or {}
                    except Exception as exc:
                        report = {"report_error": type(exc).__name__}
            _write_json(output_directory / "strategy_report.json", report)
            minute_events = list(report.get("minute_events") or [])
            feed_fault = (report.get("feed_evidence") or {}).get("fault")
            features = [
                event
                for event in minute_events
                if str(event.get("kind") or "") in {"WARMUP", "ORDINARY_DECISION"}
            ]
            summary["run"] = {
                "seconds": round(time.monotonic() - started_mono, 3),
                "run_error_type": run_exception,
            }
            summary["observation"] = {
                "feature_minutes": len(features),
                "feed_evidence_fault": feed_fault,
            }
            summary["provider_operations"]["market_subscriptions"] = len(market_clients)
            summary.update(
                status="BLOCKED",
                reason=(
                    "ctp_source_clock_mapping_unqualified"
                    if run_exception is None
                    else "service_cerebro_run_failed"
                ),
                clock_qualification="NOT_QUALIFIED",
                external_request_counts={"order_write": 0},
            )
            if run_exception is None:
                summary["service_clock_reason"] = "ctp_receive_clock_mapping_unavailable"
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                summary.update(status="UNKNOWN", reason="service_run_interrupted")
                result_code = EXIT_UNKNOWN
            else:
                summary.update(
                    status="BLOCKED",
                    reason=_safe_code(exc, "service_backend_failed"),
                    error_type=type(exc).__name__,
                )
            result_code = EXIT_BLOCKED if not isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)) else EXIT_UNKNOWN
        finally:
            broker_health, store_health, stop_errors = _stop_broker_and_store(
                broker,
                store,
                float(timeout_config.get("stop_seconds") or 10.0),
            )
            cleanup_errors.extend(stop_errors)
            if broker is not None:
                summary["broker_shutdown"] = {
                    key: broker_health.get(key)
                    for key in ("status", "reason", "store_shutdown_state")
                    if isinstance(broker_health, Mapping) and key in broker_health
                }
            confirmed_store_state = (
                store_health.get("shutdown_state")
                if isinstance(store_health, Mapping)
                else broker_health.get("store_shutdown_state")
                if isinstance(broker_health, Mapping)
                else None
            )
            if confirmed_store_state is not None:
                summary["store_shutdown_state"] = confirmed_store_state
            if broker is None and store is None and proxy is not None:
                try:
                    proxy.disconnect()
                except Exception as exc:
                    cleanup_errors.append(f"proxy_close:{_safe_code(exc, type(exc).__name__)}")
            elif broker is None and store is None:
                for client in market_clients:
                    try:
                        client.close()
                    except Exception as exc:
                        cleanup_errors.append(
                            f"market_client_close:{_safe_code(exc, type(exc).__name__)}"
                        )
                if account_client is not None:
                    try:
                        account_client.close()
                    except Exception as exc:
                        cleanup_errors.append(
                            f"account_client_close:{_safe_code(exc, type(exc).__name__)}"
                        )
            if runtime is not None:
                try:
                    runtime.close()
                except Exception as exc:
                    cleanup_errors.append(f"runtime_close:{_safe_code(exc, type(exc).__name__)}")
                if (
                    runtime.state != "closed"
                    or runtime.cleanup_failures != 0
                    or runtime.unregister_uncertainties != 0
                    or runtime.unknown_registration_count != 0
                ):
                    cleanup_errors.append("runtime_terminal_state_unconfirmed")
            if cleanup_errors:
                for item in (proxy, runtime, *market_clients, account_client, store, broker):
                    if item is not None and not any(value is item for value in runner_module._OBSERVATION_CLEANUP_KEEPALIVE):
                        runner_module._OBSERVATION_CLEANUP_KEEPALIVE.append(item)
                prior = {key: summary.get(key) for key in ("status", "reason") if summary.get(key) is not None}
                summary.update(
                    status="BLOCKED",
                    reason="service_cleanup_uncertain",
                    cleanup_prior_outcome=prior,
                    cleanup_errors=cleanup_errors,
                )
                result_code = EXIT_BLOCKED
            else:
                summary["cleanup_status"] = "closed"
                summary["runtime_state"] = "closed" if runtime is not None else "not_started"
            summary["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            _write_json(output_directory / "run.json", summary)
            runner_module._json_print(summary)
        return result_code
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            reason = "service_preflight_interrupted"
        else:
            reason = _safe_code(exc, "service_preflight_failed")
        runner_module._json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": reason,
                "error_type": type(exc).__name__,
                "clock_qualification": "NOT_QUALIFIED",
                "entry_tier": dict(decision_evidence),
                "write_grant_result": "refused_no_order_path_by_contract",
            }
        )
        return EXIT_UNKNOWN if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)) else EXIT_BLOCKED
