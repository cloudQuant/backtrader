"""Backtrader bindings for SDK-owned read-only service observation clients.

The SDK owns runtime and service clients. This adapter binds their neutral
market resources to Backtrader Store/Feed contracts without parsing venue data.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

__all__ = (
    "ServiceObservationSession", "open_service_read_session",
)

_KEEPALIVE: list[tuple[Any, ...]] = []
_KEEPALIVE_LOCK = threading.Lock()


def _error(code: str) -> Exception:
    from bt_api_py.service_observation_assembly import ServiceObservationError

    return ServiceObservationError(code)


class ServiceObservationSession:
    """Bind one SDK observation handle to its Backtrader Store lifecycle."""

    def __init__(self, clients: Any, *, proxy: Any, store: Any,
                 bindings: Mapping[str, Any], timeout_seconds: float) -> None:
        self._clients = clients
        self.runtime = clients.runtime
        self.account_client = clients.account_client
        self.metadata = clients.metadata
        self.market_clients = clients.market_clients
        self.proxy = proxy
        self.store = store
        self.bindings = MappingProxyType(dict(bindings))
        self.timeout_seconds = timeout_seconds
        self.cleanup_report: Mapping[str, Any] | None = None

    @property
    def account_view(self) -> Any:
        return self._clients.account_view

    def __enter__(self) -> ServiceObservationSession:
        self._clients.assert_owner()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def _assert_open(self) -> None:
        self._clients.assert_owner()
        if self.cleanup_report is not None:
            raise _error("SERVICE_SESSION_CLOSED")

    def refresh_account(self) -> Any:
        self._assert_open()
        return self._clients.refresh_account()

    def subscribe(self, dataname: str) -> Any:
        self._assert_open()
        if self._clients.is_subscribed(dataname):
            return self._clients.descriptor(dataname)
        if self.proxy is not None and dataname in self.bindings:
            self.proxy.subscribe(dataname)
            return self._clients.accept_external_subscription(dataname)
        return self._clients.subscribe(dataname)

    def initial_snapshot(self, dataname: str) -> Any:
        self._assert_open()
        return self._clients.initial_snapshot(dataname)

    def poll(self, dataname: str, *, timeout_ms: int = 0) -> Any:
        self._assert_open()
        if not self._clients.is_subscribed(dataname):
            self.subscribe(dataname)
        if self.proxy is not None and dataname in self.bindings:
            from bt_api_py.service_market_bindings import ServiceFeedBinding, ServiceOrderBookBinding

            binding = self.bindings[dataname]
            if type(binding) is ServiceFeedBinding:
                return self.proxy.poll_bar(dataname)
            if type(binding) is ServiceOrderBookBinding:
                return self.proxy.poll_orderbook(dataname)
        return self._clients.poll(dataname, timeout_ms=timeout_ms)

    def poll_orderbook(self, dataname: str) -> Any:
        from bt_api_py.service_market_bindings import ServiceOrderBookBinding

        self._assert_open()
        if self.proxy is None or type(self.bindings.get(dataname)) is not ServiceOrderBookBinding:
            raise _error("SERVICE_ORDERBOOK_BINDING_UNAVAILABLE")
        return self.poll(dataname)

    def descriptor(self, dataname: str) -> Any:
        self._assert_open()
        return self._clients.descriptor(dataname)

    def close(self) -> Mapping[str, Any]:
        self._clients.assert_owner()
        if self.cleanup_report is not None:
            return self.cleanup_report
        external_facades = self.store is not None or self.proxy is not None
        facades_confirmed = not external_facades
        facade_errors: list[str] = []
        if self.store is not None:
            try:
                health = self.store.stop(timeout=self.timeout_seconds)
                facades_confirmed = isinstance(health, Mapping) and health.get("shutdown_state") == "PASS"
                if not facades_confirmed:
                    facade_errors.append("store_shutdown_unconfirmed")
            except Exception:
                facades_confirmed = False
                facade_errors.append("store_stop_failed")
        elif self.proxy is not None:
            try:
                self.proxy.disconnect()
                facades_confirmed = True
            except Exception:
                facades_confirmed = False
                facade_errors.append("facade_close_failed")
        try:
            result = self._clients.close(
                close_facades=not external_facades, facades_confirmed=facades_confirmed,
                facade_errors=tuple(facade_errors),
            )
        except Exception:
            result = self._clients.close_report
            with _KEEPALIVE_LOCK:
                _KEEPALIVE.append((self._clients, self.proxy, self.store, self.bindings))
            self.cleanup_report = result
            raise _error("SERVICE_CLEANUP_UNCONFIRMED") from None
        self.cleanup_report = result
        return result


def open_service_read_session(
    service_config: Mapping[str, Any],
    *,
    instruments: tuple[Any, ...] | list[Any],
    provider_route: str | None = None,
    allow_write: bool = False,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> ServiceObservationSession:
    """Bind SDK observation clients to optional Backtrader Feed resources."""
    from bt_api_py.service_observation_clients import open_service_observation_clients

    if allow_write is not False:
        raise _error("SERVICE_OBSERVATION_WRITE_UNSUPPORTED")
    if not isinstance(service_config, Mapping) or not isinstance(service_config.get("account"), Mapping):
        raise _error("SERVICE_ACCOUNT_CONFIG_INVALID")
    account = service_config["account"]
    neutral_fields = ("mount", "account_ref", "key", "required_coverage")
    if any(name not in account for name in neutral_fields):
        raise _error("SERVICE_ACCOUNT_CONFIG_INVALID")
    # Do not start a service client when a Store-bound feed has no supported
    # neutral channel. Provider metadata alone cannot authorize a tick bridge.
    if type(instruments) in (tuple, list):
        for item in instruments:
            if getattr(item, "resource", None) is None:
                continue
            key = getattr(item, "market_key", None)
            channel = key.get("channel") if isinstance(key, Mapping) else getattr(key, "channel", None)
            if channel not in {"bar", "orderbook"}:
                raise _error("SERVICE_MARKET_CHANNEL_UNSUPPORTED")
    sdk_config = dict(service_config)
    sdk_config["account"] = {name: account[name] for name in neutral_fields}
    clients = open_service_observation_clients(
        sdk_config, instruments=instruments, provider_route=provider_route,
        allow_write=allow_write, environ=environ, timeout_seconds=timeout_seconds,
    )
    proxy = store = None
    bindings: dict[str, Any] = {}
    try:
        if clients.resources:
            if len(clients.resources) != len(instruments):
                raise _error("SERVICE_FEED_RESOURCE_SET_INCOMPLETE")
            from bt_api_py.service_market_bindings import ServiceFeedBinding, ServiceOrderBookBinding

            from .service_read_proxy import ServiceReadProxy
            from ..stores.btapistore import BtApiStore

            for item in instruments:
                key = clients.market_keys[item.subscription_id]
                resource = clients.resources[item.subscription_id]
                if item.qty_unit is None:
                    raise _error("SERVICE_FEED_BINDING_INVALID")
                if key.channel == "bar":
                    bindings[item.subscription_id] = ServiceFeedBinding(
                        market_client=clients.market_clients[item.subscription_id], resource=resource,
                        qty_unit=item.qty_unit, timeframe=key.timeframe,
                        quantity_multiplier=item.quantity_multiplier,
                    )
                elif key.channel == "orderbook":
                    bindings[item.subscription_id] = ServiceOrderBookBinding(
                        market_client=clients.market_clients[item.subscription_id], resource=resource,
                        qty_unit=item.qty_unit, quantity_multiplier=item.quantity_multiplier,
                        max_depth=key.depth, max_event_age_seconds=item.max_event_age_seconds,
                    )
                else:
                    raise _error("SERVICE_MARKET_CHANNEL_UNSUPPORTED")
            proxy = ServiceReadProxy(
                clients.account_client, bindings,
                valuation_currency=account["valuation_currency"], position_mode=account["position_mode"],
            )
            store = BtApiStore(api=proxy)
            proxy.connect()
            clients.account_view = clients.account_client.snapshot()
        return ServiceObservationSession(
            clients, proxy=proxy, store=store, bindings=bindings, timeout_seconds=float(timeout_seconds),
        )
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        session = ServiceObservationSession(
            clients, proxy=proxy, store=store, bindings=bindings, timeout_seconds=float(timeout_seconds),
        )
        try:
            session.close()
        except Exception:
            pass
        from bt_api_py.service_observation_assembly import ServiceObservationError

        if isinstance(error, ServiceObservationError):
            raise
        raise ServiceObservationError("SERVICE_READ_PROXY_CONFIG_INVALID") from None
