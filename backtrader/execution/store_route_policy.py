"""Validate Backtrader Store configuration against the live SDK route set.

This policy owns no API, feed, provider, or session state. The Store remains
the single owner of those values and passes its current route/lifecycle
attributes through the existing adapter boundary. A matching route name is
only a configuration check; it does not establish account identity or write
authority.
"""

from __future__ import annotations

import weakref
from collections.abc import Mapping
from typing import Any, Callable, Type


class StoreRouteIdentityPolicy:
    """Compare one Store's explicit routes with the selected facade routes."""

    def __init__(
        self,
        store: Any,
        *,
        error_type: Type[Exception],
        is_supported_api_facade: Callable[[Any], Any],
        api_unset: Any,
    ) -> None:
        if store is None or not callable(error_type) or not callable(is_supported_api_facade):
            raise TypeError("Store route policy requires its Store and validation callbacks")
        self._store_ref = weakref.ref(store)
        self._error_type = error_type
        self._is_supported_api_facade = is_supported_api_facade
        self._api_unset = api_unset

    @staticmethod
    def write_route_names(routes, *, error_type: Type[Exception]):
        """Return normalized exchange roots from route keys or route values."""
        from bt_api_py.route_identity_projection import write_route_names

        return write_route_names(
            routes, error_type=error_type,
            error_message="Store/API route identity is unavailable; write dispatch is disabled",
        )

    @staticmethod
    def write_route_keys(routes, *, error_type: Type[Exception]):
        """Return normalized full route keys for snapshot comparison."""
        from bt_api_py.route_identity_projection import write_route_keys

        return write_route_keys(
            routes, error_type=error_type,
            error_message="Store/API route identity is unavailable; write dispatch is disabled",
        )

    def facade_exchange_names(self, api: Any):
        """Read the facade's public route-name projection without config values."""
        from bt_api_py.route_identity_projection import facade_exchange_names

        return facade_exchange_names(api, error_type=self._error_type)

    def _expected_write_route_names(self, store):
        """Resolve local route identity without consulting an API object."""
        provider = str(getattr(store, "provider", "") or "").strip().lower()
        config = getattr(store, "_config", {})
        api_kwargs = getattr(store, "_api_kwargs", {})
        if not isinstance(config, Mapping) or not isinstance(api_kwargs, Mapping):
            raise self._error_type(
                "Store/API route identity is unavailable; write dispatch is disabled"
            )
        if provider == "btapi":
            sdk_exchanges = getattr(store, "_sdk_exchanges", {})
            sdk_routes = getattr(store, "_sdk_routes", {})
            if not isinstance(sdk_exchanges, Mapping) or not isinstance(sdk_routes, Mapping):
                raise self._error_type(
                    "Store/API route identity is unavailable; write dispatch is disabled"
                )
            try:
                symbol_routes = sdk_routes.values()
            except Exception as exc:
                raise self._error_type(
                    "Store/API route identity is unavailable; write dispatch is disabled"
                ) from exc
            return self.write_route_names(
                sdk_exchanges, error_type=self._error_type
            ) | self.write_route_names(symbol_routes, error_type=self._error_type)
        return self.write_route_names((provider,), error_type=self._error_type)

    def assert_identity(
        self,
        *,
        require_live_route: bool = False,
        expected_api: Any = None,
    ) -> None:
        """Reject a configured/live route mismatch before a Store handoff."""
        store = self._store_ref()
        if store is None:
            raise RuntimeError("Store route policy owner is no longer available")
        if (
            getattr(store, "_managed_runtime_borrowed_api", None) is not None
            and getattr(store, "_managed_runtime_stopped", False)
        ):
            raise self._error_type("managed_runtime_store_session_already_stopped")
        api = getattr(store, "_api", None)
        if expected_api is not self._api_unset and api is not expected_api:
            raise self._error_type(
                "Store/API instance changed before write dispatch; write dispatch is disabled"
            )
        if api is not None and getattr(store, "_sdk_mode", False) and not getattr(
            store, "_service_read_only", False
        ):
            api_is_bt_api, api_is_read_proxy = self._is_supported_api_facade(api)
            if not api_is_bt_api or api_is_read_proxy:
                raise self._error_type(
                    "Store/API instance no longer implements the public unified facade"
                )
        require_live_route = require_live_route or bool(
            getattr(store, "_sdk_mode", False)
            and not getattr(store, "_service_read_only", False)
        )
        expected = self._expected_write_route_names(store)
        sdk_exchanges = getattr(store, "_sdk_exchanges", {})
        if not isinstance(sdk_exchanges, Mapping):
            raise self._error_type(
                "Store/API route identity is unavailable; write dispatch is disabled"
            )
        snapshot = self.write_route_names(sdk_exchanges, error_type=self._error_type)
        snapshot_keys = self.write_route_keys(sdk_exchanges, error_type=self._error_type)
        live_routes = None
        live_keys = None
        if api is not None:
            try:
                live_exchange_names = self.facade_exchange_names(api)
            except Exception as exc:
                raise self._error_type(
                    "Store/API route identity is unavailable; write dispatch is disabled"
                ) from exc
            live_routes = self.write_route_names(
                live_exchange_names, error_type=self._error_type
            )
            live_keys = self.write_route_keys(live_exchange_names, error_type=self._error_type)
        lazy_owned_api_pending = bool(
            api is None
            and getattr(store, "_sdk_mode", False)
            and getattr(store, "_sdk_owned_api", False)
            and not getattr(store, "_connected", False)
            and expected_api is self._api_unset
        )
        from bt_api_py.route_identity_projection import assert_route_sets_current

        assert_route_sets_current(
            expected=expected,
            snapshot=snapshot,
            snapshot_keys=snapshot_keys,
            live_routes=live_routes,
            live_keys=live_keys,
            require_live_route=require_live_route,
            api_present=api is not None,
            lazy_owned_api_pending=lazy_owned_api_pending,
            error_type=self._error_type,
        )


__all__ = ("StoreRouteIdentityPolicy",)
