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
import time
import uuid
from typing import Any, Deque, Dict, Iterable, List, Optional

from ..events import TickEvent
from .livestore import LiveStoreBase


_PLACEHOLDER_PROVIDERS = frozenset({"futu", "oanda", "vc"})
_CTP_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"})
_CTP_TZ = _dt.timezone(_dt.timedelta(hours=8))


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


def _coerce_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with a stable fallback."""
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_ctp_symbol(symbol: Any) -> tuple[str, str]:
    """Split a CTP dataname into instrument and exchange components."""
    text = str(symbol or "").strip()
    if not text:
        return "", ""

    if "." in text:
        instrument, exchange = text.split(".", 1)
        return instrument.strip(), exchange.strip().upper()

    if "_" in text:
        exchange, instrument = text.split("_", 1)
        exchange = exchange.strip().upper()
        if exchange in _CTP_EXCHANGES:
            return instrument.strip(), exchange

    return text, ""


def _infer_tick_direction(
    last_price: float,
    bid_price: Optional[float],
    ask_price: Optional[float],
    previous_price: Optional[float],
) -> str:
    """Infer an approximate aggressive side for a market data tick."""
    if ask_price and last_price >= ask_price:
        return "buy"
    if bid_price and last_price <= bid_price:
        return "sell"
    if previous_price is not None:
        return "buy" if last_price >= previous_price else "sell"
    return "buy"


def _build_ctp_tick_datetime(payload: Any) -> _dt.datetime:
    """Build a timezone-aware datetime from a CTP depth market data tick."""
    update_time = str(getattr(payload, "UpdateTime", "") or "").strip() or "00:00:00"
    millisec = max(0, min(_coerce_int(getattr(payload, "UpdateMillisec", 0), 0), 999))

    for day_value in (
        str(getattr(payload, "ActionDay", "") or "").strip(),
        str(getattr(payload, "TradingDay", "") or "").strip(),
    ):
        if len(day_value) != 8 or not day_value.isdigit():
            continue
        try:
            dt_value = _dt.datetime.strptime(f"{day_value} {update_time}", "%Y%m%d %H:%M:%S")
            return dt_value.replace(microsecond=millisec * 1000, tzinfo=_CTP_TZ)
        except ValueError:
            continue

    return _dt.datetime.now(_CTP_TZ)

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
            self._positions_cache = []
            self._tick_queues = collections.defaultdict(collections.deque)
            self._instrument_aliases = collections.defaultdict(set)
            self._subscribed_aliases = set()
            self._last_total_volume = {}
            self._last_tick_price = {}

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
            self.md_client.on_tick = self._handle_md_tick

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

            if not self.md_client.wait_ready(timeout=20):
                raise BtApiStoreError("CTP market data login did not become ready within 20s")
            if not self.trader_client.wait_ready(timeout=20):
                raise BtApiStoreError("CTP trader login did not become ready within 20s")

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
                instruments = []
                for symbol in symbols:
                    alias = str(symbol or "").strip()
                    instrument, _exchange = _split_ctp_symbol(alias)
                    if not instrument:
                        continue
                    self._subscribed_aliases.add(alias)
                    self._instrument_aliases[instrument].add(alias)
                    instruments.append(instrument)

                if instruments:
                    self.md_client.subscribe(sorted(set(instruments)))

        def poll_tick(self, symbol):
            """Poll the next live tick for a subscribed symbol."""
            queue = self._tick_queues.get(str(symbol), None)
            if not queue:
                return None
            return queue.popleft()

        def get_next_tick(self, symbol):
            """Alias for poll_tick."""
            return self.poll_tick(symbol)

        def has_pending_tick(self, symbol):
            """Return whether a subscribed symbol has queued live ticks."""
            queue = self._tick_queues.get(str(symbol), None)
            return bool(queue)

        def supports_live_ticks(self, symbol):
            """Return whether a symbol has an active live tick subscription."""
            return str(symbol) in self._subscribed_aliases

        def get_balance(self):
            """Get account balance."""
            if self.trader_client and self.trader_client.is_ready:
                account = self.trader_client.query_account(timeout=5)
                if account is not None:
                    available = _coerce_float(getattr(account, "Available", None))
                    balance = _coerce_float(getattr(account, "Balance", None), available)
                    self._balance_cache = {
                        "cash": available,
                        "value": balance,
                    }
            return dict(self._balance_cache)

        def get_account(self):
            """Get account info (alias for get_balance)."""
            return self.get_balance()

        def get_positions(self):
            """Get positions."""
            if not self.trader_client or not self.trader_client.is_ready:
                return list(self._positions_cache)

            rows = self.trader_client.query_positions(timeout=5)
            aggregated = {}
            for row in rows or []:
                instrument = str(getattr(row, "InstrumentID", "") or "").strip()
                if not instrument:
                    continue

                direction_code = str(getattr(row, "PosiDirection", "") or "")
                direction = "short" if direction_code in {"3", "Short"} else "long"
                key = (instrument, direction)

                volume = _coerce_float(getattr(row, "Position", None))
                if volume <= 0:
                    continue

                cost = _coerce_float(
                    getattr(row, "PositionCost", None),
                    _coerce_float(getattr(row, "OpenCost", None)),
                )

                item = aggregated.setdefault(
                    key,
                    {
                        "instrument": instrument,
                        "direction": direction,
                        "volume": 0.0,
                        "cost": 0.0,
                    },
                )
                item["volume"] += volume
                item["cost"] += cost

            self._positions_cache = []
            for item in aggregated.values():
                volume = item["volume"] or 0.0
                avg_price = (item["cost"] / volume) if volume else 0.0
                self._positions_cache.append(
                    {
                        "instrument": item["instrument"],
                        "direction": item["direction"],
                        "volume": volume,
                        "price": avg_price,
                    }
                )

            return list(self._positions_cache)

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

        def _handle_md_tick(self, payload):
            """Convert a raw CTP depth market data callback into queued TickEvents."""
            instrument = str(
                getattr(payload, "InstrumentID", "") or getattr(payload, "ExchangeInstID", "") or ""
            ).strip()
            if not instrument:
                return

            tick_dt = _build_ctp_tick_datetime(payload)
            last_price = _coerce_float(getattr(payload, "LastPrice", None))
            if last_price <= 0:
                return

            exchange_id = str(getattr(payload, "ExchangeID", "") or "").strip().upper()
            total_volume = _coerce_float(getattr(payload, "Volume", None))
            previous_total = self._last_total_volume.get(instrument)
            tick_volume = max(total_volume - previous_total, 0.0) if previous_total is not None else 0.0
            self._last_total_volume[instrument] = total_volume

            bid_price = _coerce_float(getattr(payload, "BidPrice1", None), 0.0) or None
            ask_price = _coerce_float(getattr(payload, "AskPrice1", None), 0.0) or None
            direction = _infer_tick_direction(
                last_price,
                bid_price,
                ask_price,
                self._last_tick_price.get(instrument),
            )
            self._last_tick_price[instrument] = last_price

            aliases = tuple(self._instrument_aliases.get(instrument) or (instrument,))
            for alias in aliases:
                event = TickEvent(
                    timestamp=tick_dt.timestamp(),
                    symbol=alias,
                    exchange=exchange_id,
                    asset_type="futures",
                    local_time=time.time(),
                    price=last_price,
                    volume=tick_volume,
                    direction=direction,
                    trade_id=(
                        f"{instrument}-{getattr(payload, 'UpdateTime', '')}-"
                        f"{getattr(payload, 'UpdateMillisec', 0)}-{int(total_volume)}"
                    ),
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_volume=_coerce_float(getattr(payload, "BidVolume1", None), 0.0) or None,
                    ask_volume=_coerce_float(getattr(payload, "AskVolume1", None), 0.0) or None,
                )
                event.datetime = tick_dt.replace(tzinfo=None)
                event.instrument_id = instrument
                event.exchange_id = exchange_id
                event.openinterest = _coerce_float(getattr(payload, "OpenInterest", None))
                event.turnover = _coerce_float(getattr(payload, "Turnover", None))
                event.trading_day = str(getattr(payload, "TradingDay", "") or "")
                event.action_day = str(getattr(payload, "ActionDay", "") or "")
                event.update_time = str(getattr(payload, "UpdateTime", "") or "")
                event.update_millisec = _coerce_int(getattr(payload, "UpdateMillisec", 0), 0)
                self._tick_queues[alias].append(event)

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
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
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
        self.contract_metadata = {
            str(key): dict(value or {}) for key, value in (contract_metadata or {}).items()
        }
        self.session_id = (
            f"{self.provider}-"
            f"{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )

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
        if self._connected:
            self.emit_runtime_event("store_disconnect_requested", status="disconnecting")

        if self._api is not None:
            if hasattr(self._api, "disconnect"):
                self._api.disconnect()
            elif hasattr(self._api, "stop"):
                self._api.stop()

        self._connected = False
        self._started = False
        self.emit_runtime_event("store_disconnected", status="disconnected")

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
            self.emit_runtime_event(
                "market_data_subscribe_request",
                details={"data_name": dataname},
                status="submitted",
            )

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

    def poll_tick(self, dataname: str):
        """Poll a single live tick from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if hasattr(api, "poll_tick"):
            return api.poll_tick(dataname)
        if hasattr(api, "get_next_tick"):
            return api.get_next_tick(dataname)
        return None

    def has_pending_tick(self, dataname: str) -> bool:
        """Return whether the API has queued live ticks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "has_pending_tick"):
            return bool(api.has_pending_tick(dataname))
        return False

    def supports_live_ticks(self, dataname: str) -> bool:
        """Return whether a symbol is configured for live tick streaming."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "supports_live_ticks"):
            return bool(api.supports_live_ticks(dataname))
        return False

    def submit_order(self, order):
        """Submit a backtrader order through the unified API."""
        api = self._ensure_api_ready()
        payload = self._order_to_payload(order)
        order_ref = getattr(order, "ref", None)
        self.emit_runtime_event(
            "order_submit_request",
            order_ref=order_ref,
            details=dict(payload),
            status="submitted",
        )

        try:
            if hasattr(api, "submit_order"):
                response = api.submit_order(payload)
            elif hasattr(api, "create_order"):
                response = api.create_order(**payload)
            else:
                raise BtApiStoreError("Underlying bt_api_py client does not support order submission")
        except Exception as exc:
            self.emit_runtime_event(
                "order_reject_remote",
                level="ERROR",
                order_ref=order_ref,
                details=dict(payload),
                error_code=type(exc).__name__,
                error_msg=str(exc),
                status="rejected",
            )
            raise

        external_order_id = self._extract_external_order_id(response)
        self.emit_runtime_event(
            "order_submit_accepted",
            order_ref=external_order_id or order_ref,
            details=dict(payload),
            status="accepted",
        )
        return response


    def cancel_order(self, order):
        """Cancel a submitted order through the unified API."""
        api = self._ensure_api_ready()
        order_ref = getattr(order.info, "external_order_id", None) or getattr(order, "ref", None)
        dataname = self._extract_dataname(order.data)
        details = {"order_ref": order_ref, "data_name": dataname}
        self.emit_runtime_event(
            "order_cancel_request",
            order_ref=order_ref,
            details=details,
            status="submitted",
        )

        try:
            if hasattr(api, "cancel_order"):
                response = api.cancel_order(order_ref, dataname=dataname)
            else:
                raise BtApiStoreError(
                    "Underlying bt_api_py client does not support order cancellation"
                )
        except Exception as exc:
            self.emit_runtime_event(
                "order_cancel_reject_remote",
                level="ERROR",
                order_ref=order_ref,
                details=details,
                error_code=type(exc).__name__,
                error_msg=str(exc),
                status="rejected",
            )
            raise

        self.emit_runtime_event(
            "order_cancel_submitted",
            order_ref=order_ref,
            details=details,
            status="accepted",
        )
        return response

    def push_live_bar(self, dataname: str, bar: Any):
        """Push a live bar into the local queue, primarily for tests."""
        self._live_bars[dataname].append(_normalize_bar(bar))

    def set_history(self, dataname: str, bars: Iterable[Any]):
        """Replace the local historical bar cache, primarily for tests."""
        self._historical_bars[dataname] = collections.deque(_normalize_bar(bar) for bar in bars)

    def put_notification(self, msg, *args, **kwargs):
        """Record a store-level notification."""
        self.notifs.append((msg, args, kwargs))

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
            "timestamp": _dt.datetime.utcnow().isoformat(timespec="milliseconds"),
            "event_type": str(event_type),
            "level": str(level).upper(),
            "status": status,
            "provider": self.provider,
            "session_id": self.session_id,
            "account_id_masked": self._masked_account_id(),
            "order_ref": order_ref,
            "error_code": error_code,
            "error_msg": error_msg,
            "details": dict(details or {}),
        }
        payload.update(extra)
        self.put_notification("runtime_event", event=payload)
        return payload

    def get_notifications(self):
        """Return and clear pending notifications."""
        items = list(self.notifs)
        self.notifs.clear()
        return items

    def get_contract_metadata(self, dataname: Optional[str] = None):
        """Return configured contract metadata for a single symbol or all symbols."""
        if dataname is None:
            return {key: dict(value) for key, value in self.contract_metadata.items()}

        metadata = self.contract_metadata.get(str(dataname), {})
        return dict(metadata)

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

        self.emit_runtime_event("store_connecting", status="connecting")

        try:
            if hasattr(self._api, "connect"):
                self._api.connect()
            elif hasattr(self._api, "start"):
                self._api.start()
        except Exception as exc:
            self.emit_runtime_event(
                "store_error",
                level="ERROR",
                status="connect_failed",
                error_code=type(exc).__name__,
                error_msg=str(exc),
            )
            raise

        self._connected = True
        self.emit_runtime_event("store_connected", status="connected")
        self.emit_runtime_event("store_ready", status="ready")
        if str(self.provider).lower() == "ctp":
            self.emit_runtime_event("store_auth_success", status="ready")
            self.emit_runtime_event("store_login_success", status="ready")
        self.get_balance()
        return self._api

    def _order_to_payload(self, order) -> Dict[str, Any]:
        """Convert a backtrader order into a generic bt_api_py payload."""
        price = order.price or order.created.price
        data_name = self._extract_dataname(order.data)
        payload = {
            "symbol": data_name,
            "data_name": data_name,
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(order.size),
            "price": price,
            "order_type": order.getordername().lower(),
            "valid": order.valid,
            "tradeid": getattr(order, "tradeid", 0),
        }

        if order.pricelimit is not None:
            payload["pricelimit"] = order.pricelimit

        offset = getattr(getattr(order, "info", {}), "get", lambda *_args, **_kwargs: None)("offset")
        if offset:
            payload["offset"] = offset

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

    def _masked_account_id(self) -> str:
        """Return a masked account identifier for runtime audit logs."""
        account_id = (
            self._api_kwargs.get("investor_id")
            or self._api_kwargs.get("user_id")
            or self._config.get("investor_id")
            or self._config.get("user_id")
            or ""
        )
        account_id = str(account_id)
        if len(account_id) <= 4:
            return account_id
        return f"{account_id[:2]}***{account_id[-2:]}"

    @staticmethod
    def _extract_external_order_id(response: Any):
        """Best-effort extraction of an external order id from API responses."""
        if isinstance(response, dict):
            return (
                response.get("id")
                or response.get("order_id")
                or response.get("orderId")
                or response.get("external_order_id")
            )
        return None
