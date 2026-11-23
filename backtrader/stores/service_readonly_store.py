"""Standalone non-live read-only Store encapsulating ServiceReadProxy (D62S-08a).

This class intentionally inherits :class:`LiveStoreBase` directly and does NOT
inherit :class:`BaseBtApiStore`, :class:`DirectBtApiStore`, or
:class:`GatewayBtApiStore`. It exposes read-only observation (bars, history,
order book, balances, positions) and fails closed on every write or live-broker
entrypoint.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..store import Store
from ._btapi_errors import LiveCompositionError
from .btapi_composition import _is_service_read_proxy_instance
from .livestore import LiveStoreBase

__all__ = ["ServiceReadOnlyStore"]


class ServiceReadOnlyStore(LiveStoreBase):
    """Non-live read-only Store wrapper around :class:`ServiceReadProxy`."""

    read_only = True
    service_read_only = True

    def __init__(
        self,
        read_proxy: Any,
        *,
        provider: str = "btapi",
        preserve_raw_bars: bool = False,
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        if not _is_service_read_proxy_instance(read_proxy):
            raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="service_read_proxy_required")
        self._read_proxy = read_proxy
        self.provider = provider
        self._preserve_raw_bars = bool(preserve_raw_bars)
        self._contract_metadata = dict(contract_metadata or {})
        self._connected = False
        self._stopped = False

    @property
    def read_proxy(self) -> Any:
        return self._read_proxy

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._stopped

    def start(self, data: Any = None, broker: Any = None) -> None:
        if broker is not None:
            raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_broker")
        Store.start(self, data=data, broker=None)
        starter = getattr(self._read_proxy, "start", None)
        if callable(starter):
            starter()
        self._connected = True
        self._stopped = False

    def stop(self) -> None:
        self._connected = False
        self._stopped = True
        stopper = getattr(self._read_proxy, "stop", None)
        if callable(stopper):
            stopper()

    def getbroker(self, *args: Any, **kwargs: Any) -> Any:
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_broker")

    def getdata(self, *args: Any, **kwargs: Any) -> Any:
        from ..feeds.btapifeed import BtApiFeed

        data_cls = kwargs.pop("data_cls", BtApiFeed)
        kwargs.setdefault("store", self)
        kwargs.setdefault("provider", self.provider)
        data = data_cls(*args, **kwargs)
        data._store = self
        return data

    def get_cash(self) -> float:
        getter = getattr(self._read_proxy, "get_cash", None)
        if callable(getter):
            return float(getter())
        return 0.0

    def get_value(self) -> float:
        getter = getattr(self._read_proxy, "get_value", None)
        if callable(getter):
            return float(getter())
        return 0.0

    def get_balance(self) -> Any:
        getter = getattr(self._read_proxy, "get_balance", None)
        return getter() if callable(getter) else None

    def get_positions(self) -> List[Dict[str, Any]]:
        getter = getattr(self._read_proxy, "get_positions", None)
        return list(getter()) if callable(getter) else []

    def fetch_history(self, dataname: str, **kwargs: Any) -> Any:
        fetcher = getattr(self._read_proxy, "fetch_history", None)
        if callable(fetcher):
            return fetcher(dataname, **kwargs)
        return ()

    def subscribe(self, dataname: str, **kwargs: Any) -> Any:
        sub = getattr(self._read_proxy, "subscribe", None)
        return sub(dataname, **kwargs) if callable(sub) else None

    def poll_live(self, dataname: str) -> Any:
        poller = getattr(self._read_proxy, "poll_live", None)
        return poller(dataname) if callable(poller) else None

    def poll_orderbook(self, dataname: str, **kwargs: Any) -> Any:
        poller = getattr(self._read_proxy, "poll_orderbook", None)
        return poller(dataname, **kwargs) if callable(poller) else None

    # Explicitly refuse all write entrypoints
    def make_order(self, *args: Any, **kwargs: Any) -> Any:
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_write")

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_write")

    def place_order(self, *args: Any, **kwargs: Any) -> Any:
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_write")

    def submit_order(self, *args: Any, **kwargs: Any) -> Any:
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="readonly_store_forbids_write")
