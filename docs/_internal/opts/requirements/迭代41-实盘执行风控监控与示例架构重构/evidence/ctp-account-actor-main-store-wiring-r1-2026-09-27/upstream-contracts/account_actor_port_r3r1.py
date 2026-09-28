"""Offline-only typed account actor port and preconstruction CTP route gate.

This module defines a capability boundary for a future external actor client.
It contains no transport, credential resolver, SDK import, native API, or actor
implementation. A typed fake port proves wiring only; it is not authority.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class AccountActorGateError(RuntimeError):
    """Fail-closed error before any local CTP client is connected or created."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code.replace("_", " "))


class RouteKind(str, Enum):
    CTP = "ctp"
    NON_CTP = "non_ctp"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class ActorCommandState(str, Enum):
    QUEUED = "queued"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CtpSubmitIntentV1:
    """Logical order intent. Native OrderRef/RequestID are never caller fields."""

    intent_id: str
    instrument_id: str
    exchange_id: str
    side: str
    offset: str
    hedge_flag: str
    quantity: int
    limit_price: Decimal

    def __post_init__(self) -> None:
        _required_text(self.intent_id, "intent_id")
        _required_text(self.instrument_id, "instrument_id")
        _required_text(self.exchange_id, "exchange_id")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.offset not in {"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"}:
            raise ValueError("unsupported offset")
        if self.hedge_flag not in {"SPECULATION", "ARBITRAGE", "HEDGE", "MARKET_MAKER"}:
            raise ValueError("unsupported hedge_flag")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("quantity must be a positive exact integer")
        if type(self.limit_price) is not Decimal or not self.limit_price.is_finite():
            raise ValueError("limit_price must be a finite Decimal")
        if self.limit_price <= 0:
            raise ValueError("limit_price must be positive")


@dataclass(frozen=True)
class CtpCancelIntentV1:
    """Logical cancel intent. Native OrderActionRef/RequestID are never fields."""

    cancel_intent_id: str
    runtime_order_id: str
    order_ref: str
    front_id: int
    session_id: int
    exchange_id: str
    order_sys_id: str

    def __post_init__(self) -> None:
        for name in (
            "cancel_intent_id",
            "runtime_order_id",
            "order_ref",
            "exchange_id",
            "order_sys_id",
        ):
            _required_text(getattr(self, name), name)
        if type(self.front_id) is not int or self.front_id <= 0:
            raise ValueError("front_id must be a positive exact integer")
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("session_id must be a positive exact integer")


@dataclass(frozen=True)
class ActorCommandReceiptV1:
    """Actor queue disposition; it is deliberately not a provider acknowledgement."""

    command_id: str
    state: ActorCommandState
    actor_epoch: int

    def __post_init__(self) -> None:
        _required_text(self.command_id, "command_id")
        if type(self.state) is not ActorCommandState:
            raise ValueError("state must be ActorCommandState")
        if type(self.actor_epoch) is not int or self.actor_epoch <= 0:
            raise ValueError("actor_epoch must be a positive exact integer")


class CtpAccountActorPort(ABC):
    """Typed remote-owner client seam; methods never accept local native callbacks."""

    @abstractmethod
    def submit_order(self, intent: CtpSubmitIntentV1) -> ActorCommandReceiptV1:
        """Submit one logical intent to the external account actor."""

    @abstractmethod
    def cancel_order(self, intent: CtpCancelIntentV1) -> ActorCommandReceiptV1:
        """Submit one logical cancel intent to the external account actor."""


class UnavailableCtpAccountActorPort(CtpAccountActorPort):
    """Default port. No external account actor is installed in this candidate."""

    def submit_order(self, intent: CtpSubmitIntentV1) -> ActorCommandReceiptV1:
        del intent
        raise AccountActorGateError("external_account_actor_unavailable")

    def cancel_order(self, intent: CtpCancelIntentV1) -> ActorCommandReceiptV1:
        del intent
        raise AccountActorGateError("external_account_actor_unavailable")


@dataclass(frozen=True)
class StoreRouteDescriptor:
    """Only non-secret routing facts used before Store SDK/client construction."""

    provider: str
    backend: Optional[str] = None  # noqa: UP045 - retain Python 3.8 compatibility
    config: Mapping[str, Any] = field(default_factory=dict)
    api_kwargs: Mapping[str, Any] = field(default_factory=dict)
    api: Any = None
    api_cls: Any = None
    environment_provider: Optional[str] = None  # noqa: UP045 - Python 3.8 compatibility
    environment_exchange_type: Optional[str] = None  # noqa: UP045 - Python 3.8 compatibility


# This is deliberately a small, code-owned registry. It is not inferred from
# arbitrary BtApiStore provider strings or a caller-supplied client object.
_DIRECT_NON_CTP_PROVIDERS = frozenset({"okx", "binance"})
_GATEWAY_PROVIDER_EXCHANGE = {
    "ib_web_gateway": "IB_WEB",
    "mt5_gateway": "MT5",
}
_GENERIC_GATEWAY_PROVIDERS = frozenset({"gateway"})
_CTP_PROVIDERS = frozenset({"ctp", "ctp_gateway"})
_UNSUPPORTED_PROVIDERS = frozenset({"futu", "oanda", "vc"})
_SUPPORTED_NON_CTP_VENUES = frozenset({"OKX", "BINANCE", "MT5", "IB_WEB"})
_ALL_KNOWN_VENUES = _SUPPORTED_NON_CTP_VENUES | frozenset({"CTP"})


def classify_store_route(route: StoreRouteDescriptor) -> RouteKind:
    """Classify only exact, code-owned selectors; never inspect injected clients.

    This is an offline candidate contract, not a complete BtApiStore provider
    registry. Unknown/custom providers, opaque clients/classes and malformed
    routes are ambiguous. Explicit CTP evidence wins over every non-CTP label,
    including environment overrides and nested symbol routing.
    """

    if type(route) is not StoreRouteDescriptor:
        return RouteKind.AMBIGUOUS

    provider = _selector(route.provider)
    backend = _selector(route.backend)
    env_provider = _selector(route.environment_provider)

    if (
        (route.backend is not None and type(route.backend) is not str)
        or (route.environment_provider is not None and type(route.environment_provider) is not str)
    ):
        return RouteKind.AMBIGUOUS

    # Check direct CTP selectors before considering any environment or route
    # aliases. A gateway environment override cannot downgrade a CTP request.
    if provider in _CTP_PROVIDERS or env_provider in _CTP_PROVIDERS:
        return RouteKind.CTP

    config = _exact_dict(route.config)
    api_kwargs = _exact_dict(route.api_kwargs)
    if config is None or api_kwargs is None:
        return RouteKind.AMBIGUOUS

    venues: set[str] = set()
    unknown = False
    has_selector = False
    for values in (config, api_kwargs):
        found, invalid, present = _collect_config_routes(values)
        venues.update(found)
        unknown = unknown or invalid
        has_selector = has_selector or present

    env_exchange = _venue(route.environment_exchange_type)
    if route.environment_exchange_type is not None:
        if not env_exchange:
            unknown = True
        else:
            venues.add(env_exchange)
            has_selector = True

    # Route maps can reveal CTP even if the top-level selector appears safe.
    if "CTP" in venues:
        return RouteKind.CTP

    # Do not touch attributes on route.api or route.api_cls. Even a property
    # read can execute caller code before the missing-actor gate.
    if route.api is not None or route.api_cls is not None:
        return RouteKind.AMBIGUOUS

    if unknown or not venues.issubset(_ALL_KNOWN_VENUES):
        return RouteKind.AMBIGUOUS
    if any(venue not in _SUPPORTED_NON_CTP_VENUES for venue in venues):
        return RouteKind.AMBIGUOUS

    # An environment-selected provider that changes a non-CTP selector is an
    # ambiguous route, not authority to silently choose another local client.
    if env_provider and env_provider != provider:
        return RouteKind.AMBIGUOUS

    if provider in _UNSUPPORTED_PROVIDERS:
        return RouteKind.UNSUPPORTED

    if provider in _DIRECT_NON_CTP_PROVIDERS:
        expected = provider.upper()
        if backend not in {"", "direct"}:
            return RouteKind.AMBIGUOUS
        if venues and venues != {expected}:
            return RouteKind.AMBIGUOUS
        return RouteKind.NON_CTP

    if provider == "btapi":
        if backend not in {"", "direct"}:
            return RouteKind.AMBIGUOUS
        # Generic multi-venue routing is safe only with a complete explicit
        # route map. No raw API/class injection is accepted above.
        return RouteKind.NON_CTP if has_selector and venues else RouteKind.AMBIGUOUS

    if provider in _GENERIC_GATEWAY_PROVIDERS:
        if backend not in {"", "gateway"}:
            return RouteKind.AMBIGUOUS
        if not has_selector:
            # BtApiStore's generic gateway wrapper defaults to CTP.
            return RouteKind.CTP
        return RouteKind.NON_CTP if venues and venues <= {"IB_WEB", "MT5"} else RouteKind.AMBIGUOUS

    expected_gateway = _GATEWAY_PROVIDER_EXCHANGE.get(provider)
    if expected_gateway:
        if backend not in {"", "gateway"}:
            return RouteKind.AMBIGUOUS
        # The alias itself is not sufficient: the configured route must match
        # it. With no explicit selector, the native gateway defaults to CTP.
        if not has_selector:
            return RouteKind.CTP
        return RouteKind.NON_CTP if venues == {expected_gateway} else RouteKind.AMBIGUOUS

    # Do not infer safety from arbitrary names, aliases, or a `_gateway` suffix.
    return RouteKind.AMBIGUOUS


def require_account_actor_before_local_client(
    route: StoreRouteDescriptor,
    actor_port: Optional[CtpAccountActorPort],  # noqa: UP045 - Python 3.8 compatibility
) -> CtpAccountActorPort:
    """Reject CTP/ambiguous routes before any local API, SDK or gateway creation."""

    kind = classify_store_route(route)
    if kind is RouteKind.NON_CTP:
        return actor_port if actor_port is not None else UnavailableCtpAccountActorPort()

    if kind is RouteKind.UNSUPPORTED:
        raise AccountActorGateError("store_provider_unsupported")
    if kind is RouteKind.AMBIGUOUS:
        raise AccountActorGateError("store_route_ambiguous")

    if actor_port is None or isinstance(actor_port, UnavailableCtpAccountActorPort):
        raise AccountActorGateError("external_account_actor_unavailable")
    if not isinstance(actor_port, CtpAccountActorPort):
        raise AccountActorGateError("typed_account_actor_port_required")
    if route.api is not None or route.api_cls is not None:
        raise AccountActorGateError("local_ctp_client_injection_forbidden")
    return actor_port


def validate_actor_receipt(
    receipt: object, *, expected_command_id: str
) -> ActorCommandReceiptV1:
    """Validate local receipt shape without elevating it to provider acknowledgement."""

    if type(receipt) is not ActorCommandReceiptV1:
        raise AccountActorGateError("actor_receipt_type_invalid")
    if receipt.command_id != expected_command_id:
        raise AccountActorGateError("actor_receipt_command_mismatch")
    return receipt


def reject_ctp_legacy_dispatch(route_kind: RouteKind) -> None:
    """Defense in depth for old private Store dispatchers."""

    if route_kind is not RouteKind.NON_CTP:
        raise AccountActorGateError("ctp_legacy_dispatch_forbidden")


def _collect_config_routes(values: dict[str, Any]) -> tuple[set[str], bool, bool]:
    venues: set[str] = set()
    unknown = False
    present = False
    for key in ("exchange_type", "exchange"):
        if key in values:
            present = True
            venue = _venue(values[key])
            if venue:
                venues.add(venue)
            else:
                unknown = True

    if "exchange_kwargs" in values:
        present = True
        raw = _exact_dict(values["exchange_kwargs"])
        if raw is None or not raw:
            unknown = True
        else:
            for key, options in raw.items():
                venue = _venue(key)
                if not venue or type(options) is not dict or venue not in _ALL_KNOWN_VENUES:
                    unknown = True
                else:
                    venues.add(venue)
                    nested, invalid = _collect_nested_selector_fields(options)
                    venues.update(nested)
                    unknown = unknown or invalid

    if "symbol_routes" in values:
        present = True
        found, invalid = _collect_symbol_routes(values["symbol_routes"])
        venues.update(found)
        unknown = unknown or invalid
    return venues, unknown, present


def _collect_symbol_routes(value: Any) -> tuple[set[str], bool]:
    if type(value) is not dict or not value:
        return set(), True
    venues: set[str] = set()
    unknown = False
    for route_value in value.values():
        if type(route_value) is str:
            venue = _venue(route_value)
            if venue:
                venues.add(venue)
            else:
                unknown = True
        elif type(route_value) is dict:
            found, invalid, present = _collect_nested_route(route_value)
            venues.update(found)
            unknown = unknown or invalid or not present
        else:
            unknown = True
    return venues, unknown


def _collect_nested_route(value: dict[str, Any]) -> tuple[set[str], bool, bool]:
    venues: set[str] = set()
    unknown = False
    present = False
    selector_keys = {"exchange_type", "exchange", "provider", "route"}
    for key, nested in value.items():
        if key in selector_keys:
            present = True
            venue = _venue(nested)
            if venue:
                venues.add(venue)
            else:
                unknown = True
        elif type(nested) is dict:
            found, invalid, child_present = _collect_nested_route(nested)
            venues.update(found)
            unknown = unknown or invalid
            present = present or child_present
        elif type(nested) is str:
            # Nested maps commonly use a symbol/route key and a venue value.
            present = True
            venue = _venue(nested)
            if venue:
                venues.add(venue)
            else:
                unknown = True
        else:
            unknown = True
    return venues, unknown, present


def _collect_nested_selector_fields(value: dict[str, Any]) -> tuple[set[str], bool]:
    """Find only route selector fields below venue options, ignoring secrets."""

    venues: set[str] = set()
    unknown = False
    selector_keys = {"exchange_type", "exchange", "provider", "route"}
    for key, nested in value.items():
        if key in selector_keys:
            venue = _venue(nested)
            if venue:
                venues.add(venue)
            else:
                unknown = True
        elif key == "symbol_routes":
            found, invalid = _collect_symbol_routes(nested)
            venues.update(found)
            unknown = unknown or invalid
        elif key == "exchange_kwargs":
            found, invalid, _present = _collect_config_routes({"exchange_kwargs": nested})
            venues.update(found)
            unknown = unknown or invalid
        elif type(nested) is dict:
            found, invalid = _collect_nested_selector_fields(nested)
            venues.update(found)
            unknown = unknown or invalid
    return venues, unknown


def _venue(value: Any) -> str:
    if type(value) is not str:
        return ""
    candidate = value.strip().partition("___")[0].upper()
    return candidate if candidate in _ALL_KNOWN_VENUES else ""


def _selector(value: Any) -> str:
    return value.strip().lower() if type(value) is str else ""


def _exact_dict(value: Any) -> Optional[dict[str, Any]]:  # noqa: UP045 - Python 3.8 compatibility
    return value if type(value) is dict else None


def _required_text(value: Any, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} is required")


__all__ = [
    "AccountActorGateError",
    "ActorCommandReceiptV1",
    "ActorCommandState",
    "CtpAccountActorPort",
    "CtpCancelIntentV1",
    "CtpSubmitIntentV1",
    "RouteKind",
    "StoreRouteDescriptor",
    "UnavailableCtpAccountActorPort",
    "classify_store_route",
    "reject_ctp_legacy_dispatch",
    "require_account_actor_before_local_client",
    "validate_actor_receipt",
]
