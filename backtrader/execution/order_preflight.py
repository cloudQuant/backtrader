"""Backtrader Store context for SDK-owned order preflight."""

from __future__ import annotations

import weakref


class _StoreOrderPreflightContext:
    """Expose only the Store inputs required by ``OrderPreflightCoordinator``.

    The context keeps a weak reference to avoid a Store -> coordinator -> Store
    ownership cycle. Unlike the former coordinator ``__getattr__`` adapter,
    every delegated field and operation is explicit here.
    """

    __slots__ = ("_store_ref",)

    def __init__(self, store):
        self._store_ref = weakref.ref(store)

    def _store(self):
        store = self._store_ref()
        if store is None:
            raise RuntimeError("order preflight Store context is no longer available")
        return store

    @property
    def api(self):
        return self._store()._api

    @property
    def sdk_mode(self):
        return self._store()._sdk_mode

    @property
    def service_read_only(self):
        return self._store()._service_read_only

    @property
    def contract_metadata(self):
        return self._store().contract_metadata

    def ensure_api_ready(self):
        return self._store()._ensure_api_ready()

    def assert_write_route_identity(self, *, expected_api, require_live_route):
        return self._store()._assert_write_route_identity(
            expected_api=expected_api,
            require_live_route=require_live_route,
        )

    def order_to_payload(self, order):
        return self._store()._order_to_payload(order)

    def resolve_sdk_route_name(self, api, exchange):
        return self._store()._resolve_sdk_route_name(api, exchange)

    def sdk_exchange(self, symbol):
        return self._store()._sdk_exchange(symbol)

    def account_session_snapshot(self, route):
        return self._store().account_session_snapshot(route)

    def get_market_instrument_key(self, symbol):
        return self._store().get_market_instrument_key(symbol)

    def sanitize_exception(self, error):
        return self._store().sanitize_exception(error)


