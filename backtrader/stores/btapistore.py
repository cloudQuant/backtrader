#!/usr/bin/env python
"""Unified bt_api_py-backed live store.

This module centralizes live trading integrations behind a single store
implementation. Venue-specific adapters such as CTP, CCXT, IB, Oanda,
Futu, and VC are intentionally removed from the public surface.
"""

from __future__ import annotations

import collections
import datetime as _dt
import importlib
from typing import Any, Deque, Dict, Iterable, List, Optional

from .livestore import LiveStoreBase


_PLACEHOLDER_PROVIDERS = frozenset({"futu", "oanda", "vc"})


class BtApiStoreError(Exception):
    """Base error for btapi store failures."""


class BtApiMissingDependencyError(ImportError, BtApiStoreError):
    """Raised when bt_api_py is required but unavailable."""


class BtApiProviderNotImplementedError(NotImplementedError, BtApiStoreError):
    """Raised when a provider is intentionally left as a placeholder."""


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float with a stable fallback."""
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_bar(bar: Any) -> Dict[str, Any]:
    """Normalize historical/live bar payloads into a common dict."""
    if isinstance(bar, dict):
        dt_value = bar.get("datetime") or bar.get("dt") or bar.get("time") or bar.get("timestamp")
        return {
            "datetime": _normalize_datetime(dt_value),
            "open": _coerce_float(bar.get("open")),
            "high": _coerce_float(bar.get("high")),
            "low": _coerce_float(bar.get("low")),
            "close": _coerce_float(bar.get("close")),
            "volume": _coerce_float(bar.get("volume")),
            "openinterest": _coerce_float(bar.get("openinterest"), 0.0),
        }

    if isinstance(bar, (list, tuple)) and len(bar) >= 6:
        return {
            "datetime": _normalize_datetime(bar[0]),
            "open": _coerce_float(bar[1]),
            "high": _coerce_float(bar[2]),
            "low": _coerce_float(bar[3]),
            "close": _coerce_float(bar[4]),
            "volume": _coerce_float(bar[5]),
            "openinterest": _coerce_float(bar[6], 0.0) if len(bar) > 6 else 0.0,
        }

    raise ValueError(f"Unsupported bar payload: {bar!r}")


def _normalize_datetime(value: Any) -> _dt.datetime:
    """Normalize timestamps to naive UTC datetimes."""
    if isinstance(value, _dt.datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return _dt.datetime.utcfromtimestamp(ts)

    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise ValueError(f"Unsupported datetime string: {value!r}") from exc

    raise ValueError(f"Unsupported datetime value: {value!r}")


def _resolve_bt_api_client(provider: str = "btapi"):
    """Resolve a client class from bt_api_py lazily."""
    try:
        module = importlib.import_module("bt_api_py")
    except ImportError as exc:
        raise BtApiMissingDependencyError(
            "bt_api_py is required for BtApiStore when no api/api_cls is provided"
        ) from exc

    # For CTP provider, return a wrapper class
    if provider.lower() == "ctp":
        return _create_ctp_wrapper_class()

    # For other providers, try to find standard client classes
    for candidate in ("BtApi", "BTApi", "BtAPI", "ApiClient", "Client"):
        client_cls = getattr(module, candidate, None)
        if client_cls is not None:
            return client_cls

    raise BtApiMissingDependencyError("bt_api_py is installed but no supported client class was found")


def _create_ctp_wrapper_class():
    """Create a wrapper class for CTP clients."""
    try:
        from bt_api_py.ctp.client import MdClient, TraderClient
    except ImportError as exc:
        raise BtApiMissingDependencyError("bt_api_py CTP support is not available") from exc

    class CtpClientWrapper:
        """Wrapper for CTP market and trade clients."""

        def __init__(self, **kwargs):
            self.md_front = kwargs.get("md_address") or kwargs.get("md_front")
            self.td_front = kwargs.get("td_address") or kwargs.get("td_front")
            self.broker_id = kwargs.get("broker_id", "")
            self.user_id = kwargs.get("investor_id") or kwargs.get("user_id", "")
            self.password = kwargs.get("password", "")
            self.app_id = kwargs.get("app_id", "simnow_client_test")
            self.auth_code = kwargs.get("auth_code", "0000000000000000")

            self.md_client = None
            self.trader_client = None
            self._connected = False
            self._balance_cache = {"cash": 0.0, "value": 0.0}
            self._positions_cache = {}

        def connect(self):
            """Connect to CTP servers."""
            if not self.md_front or not self.td_front:
                raise ValueError("CTP front addresses (md_address, td_address) are required")

            if not self.broker_id or not self.user_id or not self.password:
                raise ValueError("CTP credentials (broker_id, investor_id, password) are required")

            # Create market client
            self.md_client = MdClient(
                front=self.md_front,
                broker_id=self.broker_id,
                user_id=self.user_id,
                password=self.password,
            )

            # Create trader client
            self.trader_client = TraderClient(
                front=self.td_front,
                broker_id=self.broker_id,
                user_id=self.user_id,
                password=self.password,
                app_id=self.app_id,
                auth_code=self.auth_code,
            )

            # Start clients in non-blocking mode
            self.md_client.start(block=False)
            self.trader_client.start(block=False)

            # Wait for market client to be ready
            import time

            time.sleep(2)  # Give some time for connection to establish

            self._connected = True

        def start(self):
            """Start the clients (alias for connect)."""
            self.connect()

        def disconnect(self):
            """Disconnect from CTP servers."""
            if self.md_client:
                self.md_client.stop()
            if self.trader_client:
                self.trader_client.stop()
            self._connected = False

        def stop(self):
            """Stop the clients (alias for disconnect)."""
            self.disconnect()

        def subscribe(self, symbols):
            """Subscribe to market data."""
            if self.md_client:
                if isinstance(symbols, str):
                    symbols = [symbols]
                self.md_client.subscribe(symbols)

        def get_balance(self):
            """Get account balance."""
            # TODO: Implement actual balance query from trader_client
            return self._balance_cache

        def get_account(self):
            """Get account info (alias for get_balance)."""
            return self.get_balance()

        def get_positions(self):
            """Get positions."""
            # TODO: Implement actual position query from trader_client
            return self._positions_cache

        def fetch_bars(self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs):
            """Fetch historical bars (not implemented for CTP live)."""
            # CTP live doesn't support historical data in basic mode
            return []

        def fetch_ohlcv(self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs):
            """Fetch OHLCV data (not implemented for CTP live)."""
            # CTP live doesn't support historical data in basic mode
            return []

        def poll_bar(self, symbol):
            """Poll for next bar (not implemented)."""
            return None

        def get_next_bar(self, symbol):
            """Get next bar (not implemented)."""
            return None

        def submit_order(self, payload):
            """Submit an order."""
            # TODO: Implement order submission via trader_client
            return None

        def create_order(self, **kwargs):
            """Create an order."""
            # TODO: Implement order creation via trader_client
            return None

        def cancel_order(self, order_ref, dataname=None):
            """Cancel an order."""
            # TODO: Implement order cancellation via trader_client
            return None

    return CtpClientWrapper


class BtApiStore(LiveStoreBase):
    """Unified live store backed by bt_api_py or a supplied API object."""

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
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        historical_bars: Optional[Dict[str, Iterable[Any]]] = None,
        live_bars: Optional[Dict[str, Iterable[Any]]] = None,
        autostart: bool = False,
        **kwargs: Any,
    ):
        self.provider = provider
        self._api = api
        self._api_cls = api_cls
        self._config = dict(config or {})
        self._api_kwargs = dict(api_kwargs or {})
        # Merge extra kwargs into _api_kwargs for CTP and other providers
        if kwargs:
            self._api_kwargs.update(kwargs)
        self._cash = _coerce_float(cash)
        self._value = _coerce_float(value, self._cash)
        self._positions_cache = list(positions or [])
        self._connected = False
        self._started = False
        self._data_feeds = []
        self._broker = None
        self.notifs: Deque[Any] = collections.deque()
        self._historical_bars = collections.defaultdict(collections.deque)
        self._live_bars = collections.defaultdict(collections.deque)

        self._seed_bar_cache(self._historical_bars, historical_bars)
        self._seed_bar_cache(self._live_bars, live_bars)

        if autostart:
            self.start()

    @property
    def is_connected(self) -> bool:
        """Return whether the store is connected and ready."""
        return self._connected

    def start(self, data=None, broker=None):
        """Start the store and attach broker/feed instances."""
        if data is not None and data not in self._data_feeds:
            self._data_feeds.append(data)

        if broker is not None:
            self._broker = broker

        if not self._started:
            self._ensure_api_ready()
            self._started = True

    def stop(self):
        """Disconnect from the underlying bt_api_py client."""
        if self._api is not None:
            if hasattr(self._api, "disconnect"):
                self._api.disconnect()
            elif hasattr(self._api, "stop"):
                self._api.stop()

        self._connected = False
        self._started = False

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

    def get_cash(self) -> float:
        """Return cached available cash."""
        self.get_balance()
        return self._cash

    def get_value(self) -> float:
        """Return cached account value."""
        self.get_balance()
        return self._value

    def get_balance(self):
        """Refresh cached cash and value from the API, if available."""
        api = self._ensure_api_ready()

        if hasattr(api, "get_balance"):
            balance = api.get_balance()
        elif hasattr(api, "get_account"):
            balance = api.get_account()
        else:
            return {"cash": self._cash, "value": self._value}

        if isinstance(balance, dict):
            self._cash = _coerce_float(
                balance.get("cash", balance.get("available", balance.get("balance"))),
                self._cash,
            )
            self._value = _coerce_float(
                balance.get("value", balance.get("equity", balance.get("total"))),
                self._value,
            )
            return balance

        return {"cash": self._cash, "value": self._value}

    def getcash(self) -> float:
        """Get current cash balance."""
        self.get_balance()
        return self._cash

    def getvalue(self, datas=None) -> float:
        """Get total portfolio value."""
        self.get_balance()
        return self._value

    def get_positions(self) -> List[Dict[str, Any]]:
        """Return cached or queried positions."""
        api = self._ensure_api_ready()

        if hasattr(api, "get_positions"):
            positions = api.get_positions()
            self._positions_cache = list(positions or [])

        return list(self._positions_cache)

    def getpositions(self) -> List[Dict[str, Any]]:
        """Alias for get_positions()."""
        return self.get_positions()

    def register(self, feed):
        """Register a feed instance with this store."""
        if feed not in self._data_feeds:
            self._data_feeds.append(feed)

    def subscribe(self, dataname: str):
        """Subscribe to market data for the given symbol."""
        api = self._ensure_api_ready()

        if hasattr(api, "subscribe"):
            api.subscribe(dataname)

    def fetch_history(
        self,
        dataname: str,
        timeframe=None,
        compression: int = 1,
        since=None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch normalized historical bars for a symbol."""
        if self._historical_bars[dataname]:
            return list(self._historical_bars[dataname])

        api = self._ensure_api_ready()
        bars = []

        if hasattr(api, "fetch_bars"):
            bars = api.fetch_bars(
                dataname,
                timeframe=timeframe,
                compression=compression,
                since=since,
                limit=limit,
            )
        elif hasattr(api, "fetch_ohlcv"):
            bars = api.fetch_ohlcv(
                dataname,
                timeframe=timeframe,
                compression=compression,
                since=since,
                limit=limit,
            )

        normalized = [_normalize_bar(bar) for bar in bars or []]
        self._historical_bars[dataname].extend(normalized)
        return normalized

    def poll_live(self, dataname: str) -> Optional[Dict[str, Any]]:
        """Poll a single live bar from cache or the API."""
        if self._live_bars[dataname]:
            return self._live_bars[dataname].popleft()

        api = self._ensure_api_ready()
        if hasattr(api, "poll_bar"):
            bar = api.poll_bar(dataname)
        elif hasattr(api, "get_next_bar"):
            bar = api.get_next_bar(dataname)
        else:
            bar = None

        if bar is None:
            return None

        return _normalize_bar(bar)

    def submit_order(self, order):
        """Submit a backtrader order through the unified API."""
        api = self._ensure_api_ready()
        payload = self._order_to_payload(order)

        if hasattr(api, "submit_order"):
            return api.submit_order(payload)

        if hasattr(api, "create_order"):
            return api.create_order(**payload)

        raise BtApiStoreError("Underlying bt_api_py client does not support order submission")

    def cancel_order(self, order):
        """Cancel a submitted order through the unified API."""
        api = self._ensure_api_ready()
        order_ref = getattr(order.info, "external_order_id", None) or getattr(order, "ref", None)
        dataname = self._extract_dataname(order.data)

        if hasattr(api, "cancel_order"):
            return api.cancel_order(order_ref, dataname=dataname)

        raise BtApiStoreError("Underlying bt_api_py client does not support order cancellation")

    def push_live_bar(self, dataname: str, bar: Any):
        """Push a live bar into the local queue, primarily for tests."""
        self._live_bars[dataname].append(_normalize_bar(bar))

    def set_history(self, dataname: str, bars: Iterable[Any]):
        """Replace the local historical bar cache, primarily for tests."""
        self._historical_bars[dataname] = collections.deque(_normalize_bar(bar) for bar in bars)

    def put_notification(self, msg, *args, **kwargs):
        """Record a store-level notification."""
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        """Return and clear pending notifications."""
        items = list(self.notifs)
        self.notifs.clear()
        return items

    def _seed_bar_cache(self, target, source):
        """Seed internal bar caches from initialization data."""
        if not source:
            return

        for dataname, bars in source.items():
            target[dataname].extend(_normalize_bar(bar) for bar in bars)

    def _ensure_api_ready(self):
        """Instantiate and connect the underlying bt_api_py client on demand."""
        if self.provider in _PLACEHOLDER_PROVIDERS:
            raise BtApiProviderNotImplementedError(
                f"provider '{self.provider}' is reserved for future bt_api_py support"
            )

        if self._connected:
            return self._api

        if self._api is None:
            api_cls = self._api_cls or _resolve_bt_api_client(self.provider)
            kwargs = dict(self._config)
            kwargs.update(self._api_kwargs)
            self._api = api_cls(**kwargs)

        if hasattr(self._api, "connect"):
            self._api.connect()
        elif hasattr(self._api, "start"):
            self._api.start()

        self._connected = True
        self.get_balance()
        return self._api

    def _order_to_payload(self, order) -> Dict[str, Any]:
        """Convert a backtrader order into a generic bt_api_py payload."""
        price = order.price or order.created.price
        payload = {
            "symbol": self._extract_dataname(order.data),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(order.size),
            "price": price,
            "order_type": order.getordername().lower(),
            "valid": order.valid,
        }

        if order.pricelimit is not None:
            payload["pricelimit"] = order.pricelimit

        return payload

    @staticmethod
    def _extract_dataname(data) -> str:
        """Extract a stable symbol name from a data feed."""
        return (
            getattr(data, "_name", None)
            or getattr(data, "_dataname", None)
            or getattr(getattr(data, "p", None), "dataname", None)
            or getattr(data, "_dataname", None)
            or repr(data)
        )
