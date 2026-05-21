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
import logging
import math
import os
import re
import time
import uuid
import warnings
from copy import deepcopy
from typing import Any, Deque, Dict, Iterable, List, Optional

from ..events import TickEvent
from .livestore import LiveStoreBase

logger = logging.getLogger(__name__)


_PLACEHOLDER_PROVIDERS = frozenset({"futu", "oanda", "vc"})
_GATEWAY_PROVIDERS = frozenset({"gateway", "ctp_gateway", "mt5_gateway"})
_CTP_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"})
_CZCE_PRODUCT_PREFIXES = frozenset(
    {
        "AP",
        "CF",
        "CJ",
        "CY",
        "FG",
        "JR",
        "LR",
        "MA",
        "OI",
        "PF",
        "PK",
        "PM",
        "PX",
        "RI",
        "RM",
        "RS",
        "SA",
        "SF",
        "SM",
        "SR",
        "TA",
        "UR",
        "WH",
        "ZC",
    }
)
_CTP_TZ = _dt.timezone(_dt.timedelta(hours=8))
_CTP_OFFSET_FLAG = {
    "open": "0",
    "close": "1",
    "force_close": "2",
    "close_today": "3",
    "close_yesterday": "4",
    "force_close_yesterday": "5",
    "local_force_close": "6",
}
_CTP_OFFSET_MAP = {value: key for key, value in _CTP_OFFSET_FLAG.items()}
_CTP_DIRECTION_FLAG = {"buy": "0", "sell": "1"}
_CTP_DIRECTION_MAP = {value: key for key, value in _CTP_DIRECTION_FLAG.items()}
_CTP_ORDER_STATUS_MAP = {
    "0": "completed",
    "1": "partial",
    "2": "partial",
    "3": "accepted",
    "4": "accepted",
    "5": "canceled",
    "a": "submitted",
    "b": "submitted",
    "c": "submitted",
}

_CTP_LOGIN_FIELDS = (
    "FrontID",
    "SessionID",
    "TradingDay",
    "LoginTime",
    "BrokerID",
    "UserID",
    "SystemName",
)
_CTP_RSPINFO_FIELDS = (
    "ErrorID",
    "ErrorMsg",
)
_CTP_ORDER_FIELDS = (
    "AccountID",
    "ActiveTime",
    "ActiveTraderID",
    "ActiveUserID",
    "BranchID",
    "BrokerID",
    "BrokerOrderSeq",
    "BusinessUnit",
    "CancelTime",
    "ClearingPartID",
    "ClientID",
    "CombHedgeFlag",
    "CombOffsetFlag",
    "ContingentCondition",
    "CurrencyID",
    "Direction",
    "ExchangeID",
    "ExchangeInstID",
    "ForceCloseReason",
    "FrontID",
    "GTDDate",
    "IPAddress",
    "InsertDate",
    "InsertTime",
    "InstallID",
    "InstrumentID",
    "InvestUnitID",
    "InvestorID",
    "IsAutoSuspend",
    "IsSwapOrder",
    "LimitPrice",
    "MacAddress",
    "MinVolume",
    "NotifySequence",
    "OrderLocalID",
    "OrderMemo",
    "OrderPriceType",
    "OrderRef",
    "OrderSource",
    "OrderStatus",
    "OrderSubmitStatus",
    "OrderSysID",
    "OrderType",
    "ParticipantID",
    "RelativeOrderSysID",
    "RequestID",
    "SequenceNo",
    "SessionID",
    "SessionReqSeq",
    "SettlementID",
    "StatusMsg",
    "StopPrice",
    "SuspendTime",
    "TimeCondition",
    "TraderID",
    "TradingDay",
    "UpdateTime",
    "UserForceClose",
    "UserID",
    "UserProductInfo",
    "VolumeCondition",
    "VolumeTotal",
    "VolumeTotalOriginal",
    "VolumeTraded",
    "ZCETotalTradedVolume",
    "reserve1",
    "reserve2",
    "reserve3",
)
_CTP_TRADE_FIELDS = (
    "BrokerID",
    "BrokerOrderSeq",
    "BusinessUnit",
    "ClearingPartID",
    "ClientID",
    "Direction",
    "ExchangeID",
    "ExchangeInstID",
    "HedgeFlag",
    "InstrumentID",
    "InvestUnitID",
    "InvestorID",
    "OffsetFlag",
    "OrderLocalID",
    "OrderRef",
    "OrderSysID",
    "ParticipantID",
    "Price",
    "PriceSource",
    "SequenceNo",
    "SettlementID",
    "TradeDate",
    "TradeID",
    "TradeSource",
    "TradeTime",
    "TradeType",
    "TraderID",
    "TradingDay",
    "TradingRole",
    "UserID",
    "Volume",
    "reserve1",
    "reserve2",
)


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
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _coerce_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with a stable fallback."""
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_text(value: Any, default: str = "") -> str:
    """Convert vendor field values to text while suppressing noisy decode warnings."""
    if value is None:
        return default

    if isinstance(value, bytes):
        for encoding in ("utf-8", "gbk", "latin1"):
            try:
                return value.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="ignore").strip()

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Failed to convert '.*' from GBK to UTF-8\.",
            category=UnicodeWarning,
        )
        try:
            return str(value).strip()
        except Exception as e:
            logger.debug("Failed to coerce value to text: %s", e)
            return default


def _safe_text_attr(obj: Any, *attrs: str, default: str = "") -> str:
    """Return the first non-empty text attribute from a vendor object safely."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Failed to convert '.*' from GBK to UTF-8\.",
            category=UnicodeWarning,
        )
        for attr in attrs:
            try:
                value = getattr(obj, attr, None)
            except Exception as e:
                logger.debug("Failed to get attr %s from %s: %s", attr, type(obj).__name__, e)
                value = None
            text = _coerce_text(value, "")
            if text:
                return text
    return default


def _split_ctp_symbol(symbol: Any) -> tuple[str, str]:
    """Split a CTP dataname into instrument and exchange components."""
    text = _coerce_text(symbol)
    if not text:
        return "", ""

    if "." in text:
        instrument, exchange = text.split(".", 1)
        exchange = exchange.strip().upper()
        return _normalize_ctp_instrument(instrument.strip(), exchange), exchange

    if "_" in text:
        exchange, instrument = text.split("_", 1)
        exchange = exchange.strip().upper()
        if exchange in _CTP_EXCHANGES:
            return _normalize_ctp_instrument(instrument.strip(), exchange), exchange

    return _normalize_ctp_instrument(text, ""), ""


def _normalize_ctp_instrument(instrument: Any, exchange_id: Any = "") -> str:
    text = _coerce_text(instrument)
    if not text:
        return ""

    match = re.fullmatch(r"([A-Za-z]+)(\d{4})", text)
    if not match:
        return text

    prefix, digits = match.groups()
    exchange = _coerce_text(exchange_id).upper()
    if exchange == "CZCE" or (not exchange and prefix.upper() in _CZCE_PRODUCT_PREFIXES):
        return f"{prefix}{digits[-3:]}"
    return text


def _infer_tick_direction(
    last_price: float,
    bid_price: Optional[float],
    ask_price: Optional[float],
    previous_price: Optional[float],
) -> str:
    """Infer an approximate aggressive side for a market data tick."""
    if ask_price is not None and last_price >= ask_price:
        return "buy"
    if bid_price is not None and last_price <= bid_price:
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


def _ctp_field_to_dict(field: Any) -> Dict[str, Any]:
    """Convert a SWIG-generated CTP struct instance into a plain dict."""
    if field is None:
        return {}

    result = {}
    for attr in dir(field):
        if attr.startswith("_") or attr in {"this", "thisown"}:
            continue
        try:
            value = getattr(field, attr)
        except Exception as e:
            logger.debug("Failed to read CTP field attr %s: %s", attr, e)
            continue
        if callable(value):
            continue
        result[attr] = value
    return result


def _ctp_extract_fields(field: Any, attrs: Iterable[str]) -> Dict[str, Any]:
    """Read only a whitelisted subset of SWIG CTP struct attributes safely."""
    if field is None:
        return {}

    result: Dict[str, Any] = {}
    for attr in attrs:
        try:
            value = getattr(field, attr)
        except Exception as e:
            logger.debug("Failed to read CTP field attr %s: %s", attr, e)
            continue
        if callable(value):
            continue
        result[attr] = value
    return result


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
    if _is_gateway_provider(provider):
        return _create_ctp_gateway_wrapper_class()

    # For other providers, try to find standard client classes
    for candidate in ("BtApi", "BTApi", "BtAPI", "ApiClient", "Client"):
        client_cls = getattr(module, candidate, None)
        if client_cls is not None:
            return client_cls

    raise BtApiMissingDependencyError("bt_api_py is installed but no supported client class was found")


def _create_ctp_wrapper_class():
    """Create a wrapper class for CTP clients."""
    try:
        import bt_api_py.ctp.client as ctp_client_module
        from bt_api_py.ctp.client import MdClient, TraderClient
        from bt_api_py.ctp.ctp_md_api import CThostFtdcMdSpi
        from bt_api_py.ctp.ctp_structs_order import (
            CThostFtdcInputOrderActionField,
            CThostFtdcInputOrderField,
        )
        from bt_api_py.ctp.ctp_structs_query import CThostFtdcQryInstrumentField
        from bt_api_py.ctp.ctp_trader_api import CThostFtdcTraderSpi
    except ImportError as exc:
        raise BtApiMissingDependencyError("bt_api_py CTP support is not available") from exc

    def _noop_spi_method(self, *args, **kwargs):
        return None

    _spi_callback_names = {
        name
        for base_cls in (CThostFtdcMdSpi, CThostFtdcTraderSpi)
        for name in dir(base_cls)
        if name.startswith("On")
    }

    def _patch_spi_callbacks(spi_cls):
        for name in _spi_callback_names:
            if not name.startswith("On"):
                continue
            if hasattr(spi_cls, name):
                continue
            setattr(spi_cls, name, _noop_spi_method)

    _patch_spi_callbacks(ctp_client_module._MdSpi)
    _patch_spi_callbacks(ctp_client_module._TraderSpi)

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
            self._price_tick_cache = {}
            self._order_updates = collections.deque()
            self._pending_orders = {}
            self._pending_orders_by_sys_id = {}
            self._order_ref_seq = int(time.time()) % 1000000

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
            self.md_client.on_error = self._handle_md_error

            # Create trader client
            self.trader_client = TraderClient(
                front=self.td_front,
                broker_id=self.broker_id,
                user_id=self.user_id,
                password=self.password,
                app_id=self.app_id,
                auth_code=self.auth_code,
            )
            self.trader_client.on_login = self._handle_trader_login
            self.trader_client.on_order = self._handle_order
            self.trader_client.on_trade = self._handle_trade
            self.trader_client.on_error = self._handle_trader_error

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
            self._pending_orders.clear()
            self._pending_orders_by_sys_id.clear()

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

        def supports_live_streaming(self, _symbol=None):
            """Gateway/CTP market data is live-capable once the client is connected."""
            return True

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
                instrument = _safe_text_attr(row, "InstrumentID")
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

        def _get_price_tick(self, instrument):
            """Return the minimum price tick for *instrument*.

            Queries CTP via ReqQryInstrument on the first call for each
            instrument and caches the result.  Falls back to a conservative
            estimate derived from the last tick price when the query fails.
            """
            cached = self._price_tick_cache.get(instrument)
            if cached is not None:
                return cached

            # Try querying CTP for the instrument's PriceTick
            if self.trader_client and self.trader_client.is_ready:
                try:
                    import threading
                    result_event = threading.Event()
                    result_holder = {}

                    original_cb = getattr(self.trader_client, '_on_rsp_qry_instrument', None)

                    def _on_instrument(inst_field, rsp_info, request_id, is_last):
                        try:
                            if inst_field is not None:
                                iid = _safe_text_attr(inst_field, "InstrumentID")
                                pt = getattr(inst_field, 'PriceTick', 0.0)
                                if pt > 0:
                                    self._price_tick_cache[iid] = pt
                                    if iid == instrument:
                                        result_holder['price_tick'] = pt
                        except Exception as e:
                            logger.debug("Failed to process instrument response: %s", e)
                        if is_last:
                            result_event.set()

                    self.trader_client._spi.OnRspQryInstrument = _on_instrument
                    qry = CThostFtdcQryInstrumentField()
                    qry.InstrumentID = instrument
                    self.trader_client._req_id += 1
                    self.trader_client._api.ReqQryInstrument(
                        qry, self.trader_client._req_id
                    )
                    result_event.wait(timeout=3)

                    if instrument in self._price_tick_cache:
                        return self._price_tick_cache[instrument]
                except Exception as e:
                    logger.debug("Failed to query instrument info: %s", e)

            # Fallback: estimate from last tick price
            last_price = self._last_tick_price.get(instrument, 0)
            if last_price > 0:
                # Conservative estimate: smallest meaningful tick relative to price
                if last_price >= 1000:
                    tick = 1.0
                elif last_price >= 100:
                    tick = 0.5
                elif last_price >= 10:
                    tick = 0.2
                else:
                    tick = 0.01
            else:
                tick = 1.0
            self._price_tick_cache[instrument] = tick
            return tick

        def submit_order(self, payload):
            """Submit an order."""
            if not self.trader_client or not self.trader_client.is_ready:
                raise BtApiStoreError("CTP trader client is not ready")

            data_name = str(payload.get("data_name") or payload.get("symbol") or "").strip()
            instrument, exchange_id = _split_ctp_symbol(data_name)
            if not instrument:
                raise BtApiStoreError("CTP order payload requires a valid symbol")

            order_type = str(payload.get("order_type") or "limit").lower()
            if order_type not in {"limit", "market"}:
                raise BtApiStoreError(f"Unsupported CTP order type: {order_type}")

            side = str(payload.get("side") or "buy").lower()
            direction = _CTP_DIRECTION_FLAG.get(side)
            if direction is None:
                raise BtApiStoreError(f"Unsupported CTP side: {side}")

            offset = str(payload.get("offset") or "open").lower()
            offset_flag = _CTP_OFFSET_FLAG.get(offset)
            if offset_flag is None:
                raise BtApiStoreError(f"Unsupported CTP offset flag: {offset}")

            order_ref = str(payload.get("order_ref") or payload.get("bt_order_ref") or self._next_order_ref())
            volume = _coerce_int(payload.get("size"), 0)
            if volume <= 0:
                raise BtApiStoreError("CTP order volume must be positive")

            price = _coerce_float(payload.get("price"), 0.0)
            req_id = self._next_request_id()

            field = CThostFtdcInputOrderField()
            field.BrokerID = self.broker_id
            field.InvestorID = self.user_id
            field.UserID = self.user_id
            field.InstrumentID = instrument
            field.Direction = direction
            field.CombOffsetFlag = offset_flag
            field.CombHedgeFlag = "1"
            field.VolumeTotalOriginal = volume
            field.MinVolume = 1
            field.ForceCloseReason = "0"
            field.IsAutoSuspend = 0
            field.UserForceClose = 0
            field.ContingentCondition = "1"
            field.OrderRef = order_ref
            if exchange_id:
                field.ExchangeID = exchange_id

            if order_type == "market" or price <= 0:
                # Chinese futures exchanges do not support true market orders
                # (OrderPriceType="1" / AnyPrice).  Convert to a limit order
                # using the last tick price ± 5 ticks so the order is accepted
                # by the exchange.
                last_price = self._last_tick_price.get(instrument)
                if last_price is None or last_price <= 0:
                    raise BtApiStoreError(
                        f"CTP market order for {instrument} rejected: "
                        f"no recent tick price available to convert to limit order"
                    )
                price_tick = self._get_price_tick(instrument)
                slippage = price_tick * 5
                if side == "buy":
                    limit_price = last_price + slippage
                else:
                    limit_price = max(last_price - slippage, price_tick)
                field.OrderPriceType = "2"   # LimitPrice
                field.TimeCondition = "3"    # GFD (good for day)
                field.VolumeCondition = "1"  # AnyVolume
                field.LimitPrice = round(limit_price, 4)
                price = field.LimitPrice
            else:
                if price <= 0:
                    raise BtApiStoreError("CTP limit order requires a positive price")
                field.OrderPriceType = "2"
                field.TimeCondition = "3"
                field.VolumeCondition = "1"
                field.LimitPrice = price

            ret = self.trader_client.api.ReqOrderInsert(field, req_id)
            if ret != 0:
                raise BtApiStoreError(f"CTP order send failed: ret={ret}")

            self._pending_orders[order_ref] = {
                "order_ref": order_ref,
                "data_name": data_name or instrument,
                "instrument": instrument,
                "exchange_id": exchange_id,
                "side": side,
                "offset": offset,
                "price": price,
                "size": volume,
                "front_id": int(getattr(self.trader_client, "_front_id", 0) or 0),
                "session_id": int(getattr(self.trader_client, "_session_id", 0) or 0),
            }
            return {
                "order_ref": order_ref,
                "front_id": self._pending_orders[order_ref]["front_id"],
                "session_id": self._pending_orders[order_ref]["session_id"],
                "exchange_id": exchange_id,
            }

        def create_order(self, **kwargs):
            """Create an order."""
            return self.submit_order(kwargs)

        def cancel_order(self, order_ref, dataname=None):
            """Cancel an order."""
            if not self.trader_client or not self.trader_client.is_ready:
                raise BtApiStoreError("CTP trader client is not ready")

            ref = str(order_ref or "").strip()
            if not ref:
                raise BtApiStoreError("CTP cancel requires an order reference")

            pending = self._pending_orders.get(ref) or self._pending_orders_by_sys_id.get(ref, {})
            data_name = str(dataname or pending.get("data_name") or "").strip()
            instrument, exchange_id = _split_ctp_symbol(data_name)
            instrument = instrument or pending.get("instrument") or ""
            exchange_id = exchange_id or pending.get("exchange_id") or ""
            if not instrument:
                raise BtApiStoreError("CTP cancel requires a symbol")

            field = CThostFtdcInputOrderActionField()
            field.BrokerID = self.broker_id
            field.InvestorID = self.user_id
            field.UserID = self.user_id
            field.InstrumentID = instrument
            field.ActionFlag = "0"
            if exchange_id:
                field.ExchangeID = exchange_id

            order_sys_id = str(pending.get("order_sys_id") or "").strip()
            if order_sys_id:
                field.OrderSysID = order_sys_id

            field.OrderRef = str(pending.get("order_ref") or ref)
            field.FrontID = int(pending.get("front_id") or getattr(self.trader_client, "_front_id", 0) or 0)
            field.SessionID = int(
                pending.get("session_id") or getattr(self.trader_client, "_session_id", 0) or 0
            )

            req_id = self._next_request_id()
            ret = self.trader_client.api.ReqOrderAction(field, req_id)
            if ret != 0:
                raise BtApiStoreError(f"CTP cancel send failed: ret={ret}")

            return {
                "id": order_sys_id or field.OrderRef,
                "order_ref": field.OrderRef,
                "order_sys_id": order_sys_id,
                "front_id": field.FrontID,
                "session_id": field.SessionID,
                "exchange_id": exchange_id,
            }

        def poll_broker_update(self):
            """Poll a normalized broker-side order/trade/error update."""
            if not self._order_updates:
                return None
            return self._order_updates.popleft()

        def _handle_md_tick(self, payload):
            """Convert a raw CTP depth market data callback into queued TickEvents."""
            instrument = _safe_text_attr(payload, "InstrumentID", "ExchangeInstID")
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

        def _handle_md_error(self, payload):
            """Capture market-data-side runtime errors."""
            details = _ctp_extract_fields(payload, _CTP_RSPINFO_FIELDS)
            self._order_updates.append(
                {
                    "kind": "error",
                    "source": "md",
                    "error_code": _coerce_int(details.get("ErrorID"), 0),
                    "error_msg": str(details.get("ErrorMsg") or ""),
                    "details": details,
                }
            )

        def _handle_trader_login(self, payload):
            """Capture trader-login metadata for later cancel requests."""
            details = _ctp_extract_fields(payload, _CTP_LOGIN_FIELDS)
            front_id = _coerce_int(details.get("FrontID"), 0)
            session_id = _coerce_int(details.get("SessionID"), 0)
            for pending in self._pending_orders.values():
                if not pending.get("front_id"):
                    pending["front_id"] = front_id
                if not pending.get("session_id"):
                    pending["session_id"] = session_id

        def _handle_trader_error(self, payload):
            """Capture trader-side runtime errors."""
            details = _ctp_extract_fields(payload, _CTP_RSPINFO_FIELDS)
            self._order_updates.append(
                {
                    "kind": "error",
                    "source": "trader",
                    "error_code": _coerce_int(details.get("ErrorID"), 0),
                    "error_msg": str(details.get("ErrorMsg") or ""),
                    "details": details,
                }
            )

        def _handle_order(self, payload):
            """Normalize order status callbacks into broker updates."""
            details = _ctp_extract_fields(payload, _CTP_ORDER_FIELDS)
            order_ref = str(details.get("OrderRef") or "").strip()
            order_sys_id = str(details.get("OrderSysID") or "").strip()
            pending = self._pending_orders.get(order_ref, {})

            # Filter out cross-strategy order notifications: CTP sends
            # OnRtnOrder for ALL orders on the account.  Only process
            # orders that were submitted by this session (exist in
            # _pending_orders) or whose FrontID+SessionID match ours.
            if not pending:
                my_front = int(getattr(self.trader_client, "_front_id", 0) or 0)
                my_session = int(getattr(self.trader_client, "_session_id", 0) or 0)
                order_front = _coerce_int(details.get("FrontID"), 0)
                order_session = _coerce_int(details.get("SessionID"), 0)
                if my_front and my_session:
                    if order_front != my_front or order_session != my_session:
                        return

            if order_sys_id:
                self._pending_orders_by_sys_id[order_sys_id] = pending or {
                    "order_ref": order_ref,
                    "order_sys_id": order_sys_id,
                }
            if pending and order_sys_id:
                pending["order_sys_id"] = order_sys_id
            event = {
                "kind": "order",
                "order_ref": order_ref,
                "data_name": pending.get("data_name")
                or _coerce_text(details.get("InstrumentID") or details.get("ExchangeInstID") or ""),
                "instrument": _coerce_text(details.get("InstrumentID") or ""),
                "exchange_id": str(details.get("ExchangeID") or pending.get("exchange_id") or "").strip(),
                "front_id": _coerce_int(details.get("FrontID"), _coerce_int(pending.get("front_id"), 0)),
                "session_id": _coerce_int(
                    details.get("SessionID"),
                    _coerce_int(pending.get("session_id"), 0),
                ),
                "status": _CTP_ORDER_STATUS_MAP.get(str(details.get("OrderStatus") or "a"), "submitted"),
                "submit_status": str(details.get("OrderSubmitStatus") or ""),
                "status_msg": str(details.get("StatusMsg") or ""),
                "side": _CTP_DIRECTION_MAP.get(str(details.get("Direction") or "0"), "buy"),
                "offset": _CTP_OFFSET_MAP.get(
                    str(details.get("CombOffsetFlag") or "0")[:1],
                    pending.get("offset") or "open",
                ),
                "price": _coerce_float(details.get("LimitPrice"), _coerce_float(pending.get("price"), 0.0)),
                "size": _coerce_int(
                    details.get("VolumeTotalOriginal"),
                    _coerce_int(pending.get("size"), 0),
                ),
                "filled": _coerce_int(details.get("VolumeTraded"), 0),
                "remaining": _coerce_int(details.get("VolumeTotal"), 0),
                "timestamp": str(details.get("UpdateTime") or details.get("InsertTime") or ""),
                "details": details,
            }
            if order_sys_id:
                event["external_order_id"] = order_sys_id
            self._order_updates.append(event)

        def _handle_trade(self, payload):
            """Normalize trade callbacks into broker updates."""
            details = _ctp_extract_fields(payload, _CTP_TRADE_FIELDS)
            order_ref = str(details.get("OrderRef") or "").strip()
            order_sys_id = str(details.get("OrderSysID") or "").strip()
            pending = self._pending_orders.get(order_ref) or self._pending_orders_by_sys_id.get(order_sys_id, {})

            # Filter out cross-strategy trade notifications (same logic as _handle_order).
            if not pending:
                return

            event = {
                "kind": "trade",
                "trade_id": str(details.get("TradeID") or "").strip(),
                "order_ref": order_ref,
                "data_name": pending.get("data_name")
                or _coerce_text(details.get("InstrumentID") or details.get("ExchangeInstID") or ""),
                "instrument": _coerce_text(details.get("InstrumentID") or ""),
                "exchange_id": str(details.get("ExchangeID") or pending.get("exchange_id") or "").strip(),
                "side": _CTP_DIRECTION_MAP.get(str(details.get("Direction") or "0"), "buy"),
                "offset": _CTP_OFFSET_MAP.get(
                    str(details.get("OffsetFlag") or "0")[:1],
                    pending.get("offset") or "open",
                ),
                "price": _coerce_float(details.get("Price"), _coerce_float(pending.get("price"), 0.0)),
                "size": _coerce_int(details.get("Volume"), 0),
                "timestamp": str(details.get("TradeTime") or details.get("TradingDay") or ""),
                "details": details,
            }
            if order_sys_id:
                event["external_order_id"] = order_sys_id
            self._order_updates.append(event)

        def _next_order_ref(self):
            """Generate a numeric CTP client order reference."""
            self._order_ref_seq += 1
            return str(self._order_ref_seq)

        def _next_request_id(self):
            """Advance and return the next trader request id."""
            self.trader_client._req_id += 1
            return self.trader_client._req_id

    return CtpClientWrapper


def _create_ctp_gateway_wrapper_class():
    try:
        from bt_api_py.gateway.client import GatewayClient
    except ImportError as exc:
        raise BtApiMissingDependencyError("bt_api_py gateway support is not available") from exc

    class CtpGatewayClientWrapper:
        def __init__(self, **kwargs):
            self._kwargs = dict(kwargs)
            self._kwargs.setdefault("exchange_type", "CTP")
            self._kwargs.setdefault("asset_type", self._kwargs.get("asset_type", "FUTURE"))
            self._client = GatewayClient(**self._kwargs)

        def connect(self):
            self._client.connect()

        def start(self):
            self.connect()

        def disconnect(self):
            self._client.disconnect()

        def stop(self):
            self.disconnect()

        def subscribe(self, symbols):
            return self._client.subscribe(symbols)

        def poll_tick(self, symbol):
            return self._client.poll_tick(symbol)

        def get_next_tick(self, symbol):
            return self._client.get_next_tick(symbol)

        def has_pending_tick(self, symbol):
            return self._client.has_pending_tick(symbol)

        def supports_live_ticks(self, symbol):
            return self._client.supports_live_ticks(symbol)

        def supports_live_streaming(self, _symbol=None):
            return True

        def get_balance(self):
            return self._client.get_balance()

        def get_account(self):
            return self._client.get_account()

        def get_positions(self):
            return self._client.get_positions()

        def fetch_bars(self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs):
            tf = self._resolve_timeframe(timeframe, compression)
            count = int(limit or 200)
            if hasattr(self._client, "fetch_bars"):
                try:
                    return self._client.fetch_bars(symbol, timeframe=tf, count=count)
                except TypeError:
                    return self._client.fetch_bars(symbol, tf, count)
            return []

        def fetch_ohlcv(
            self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs
        ):
            return self.fetch_bars(symbol, timeframe=timeframe, compression=compression, since=since, limit=limit, **kwargs)

        def fetch_symbol_info(self, symbol):
            if hasattr(self._client, "fetch_symbol_info"):
                return self._client.fetch_symbol_info(symbol)
            return {}

        def fetch_open_orders(self):
            if hasattr(self._client, "fetch_open_orders"):
                return self._client.fetch_open_orders()
            return []

        def poll_bar(self, symbol):
            return None

        def get_next_bar(self, symbol):
            return None

        def submit_order(self, payload):
            response = self._client.submit_order(payload)
            if "data_name" in payload and "data_name" not in response:
                response["data_name"] = payload["data_name"]
            return response

        def create_order(self, **kwargs):
            return self.submit_order(kwargs)

        def cancel_order(self, order_ref, dataname=None):
            return self._client.cancel_order(order_ref, dataname=dataname)

        def poll_broker_update(self):
            return self._client.poll_broker_update()

        @staticmethod
        def _resolve_timeframe(timeframe=None, compression=None):
            """Map backtrader timeframe+compression to gateway timeframe string."""
            if isinstance(timeframe, str) and timeframe.upper() in (
                "M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1",
            ):
                return timeframe.upper()
            comp = int(compression or 1)
            try:
                import backtrader as bt
                tf_val = timeframe
                if tf_val == bt.TimeFrame.Minutes:
                    return {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4"}.get(comp, "M1")
                if tf_val == bt.TimeFrame.Days:
                    return "D1"
                if tf_val == bt.TimeFrame.Weeks:
                    return "W1"
                if tf_val == bt.TimeFrame.Months:
                    return "MN1"
            except Exception as e:
                logger.debug("Failed to resolve timeframe: %s", e)
            return "M1"

    return CtpGatewayClientWrapper


def _gateway_timeframe_str(timeframe, compression) -> str:
    """Convert backtrader timeframe + compression to a gateway string like M1, M15, H1, D1."""
    from ..dataseries import TimeFrame

    compression = int(compression or 1)
    if timeframe is None:
        return f"M{compression}"
    if timeframe == TimeFrame.Ticks:
        return "TICK"
    if timeframe == TimeFrame.Seconds:
        total_sec = compression
        if total_sec >= 86400:
            return f"D{total_sec // 86400}"
        if total_sec >= 3600:
            return f"H{total_sec // 3600}"
        return f"M{max(total_sec // 60, 1)}"
    if timeframe == TimeFrame.Minutes:
        if compression >= 60:
            return f"H{compression // 60}"
        return f"M{compression}"
    if timeframe == TimeFrame.Days:
        return f"D{compression}"
    if timeframe == TimeFrame.Weeks:
        return f"W{compression}"
    if timeframe == TimeFrame.Months:
        return f"MN{compression}"
    return f"M{compression}"


def _is_gateway_provider(provider: Any) -> bool:
    text = str(provider or "").strip().lower()
    return text in _GATEWAY_PROVIDERS or text.endswith("_gateway")


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
        account_cache_ttl: float = 0.0,
        positions_cache_ttl: float = 0.0,
        open_orders_cache_ttl: float = 0.0,
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        historical_bars: Optional[Dict[str, Iterable[Any]]] = None,
        live_bars: Optional[Dict[str, Iterable[Any]]] = None,
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        autostart: bool = False,
        **kwargs: Any,
    ):
        self.provider = self._resolve_provider(provider)
        self._api = api
        self._api_cls = api_cls
        self._config = dict(config or {})
        self._api_kwargs = dict(api_kwargs or {})
        # Merge extra kwargs into _api_kwargs for CTP and other providers
        if kwargs:
            self._api_kwargs.update(kwargs)
        self._apply_env_gateway_overrides()
        self._cash = _coerce_float(cash)
        self._value = _coerce_float(value, self._cash)
        self._account_cache_ttl = max(_coerce_float(account_cache_ttl), 0.0)
        self._positions_cache_ttl = max(_coerce_float(positions_cache_ttl), 0.0)
        self._open_orders_cache_ttl = max(_coerce_float(open_orders_cache_ttl), 0.0)
        self._positions_cache = list(positions or [])
        self._open_orders_cache = []
        seeded_at = time.monotonic() if positions or value is not None or cash else 0.0
        self._last_balance_refresh = seeded_at
        self._last_positions_refresh = seeded_at if positions else 0.0
        self._last_open_orders_refresh = 0.0
        self._connected = False
        self._started = False
        self._data_feeds = []
        self._broker = None
        self.notifs: Deque[Any] = collections.deque()
        self._historical_bars = collections.defaultdict(collections.deque)
        self._historical_query_cache: Dict[Any, List[Dict[str, Any]]] = {}
        self._live_bars = collections.defaultdict(collections.deque)
        self._subscribed_datanames = set()
        self._successful_connect_count = 0
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

    def _resolve_provider(self, provider: str) -> str:
        env_provider = str(os.environ.get("BT_STORE_PROVIDER") or "").strip().lower()
        if str(provider).strip().lower() == "ctp" and _is_gateway_provider(env_provider):
            return env_provider
        return provider

    def _apply_env_gateway_overrides(self) -> None:
        if not _is_gateway_provider(self.provider):
            return
        env_map = {
            "gateway_command_endpoint": "BT_GATEWAY_COMMAND_ENDPOINT",
            "gateway_event_endpoint": "BT_GATEWAY_EVENT_ENDPOINT",
            "gateway_market_endpoint": "BT_GATEWAY_MARKET_ENDPOINT",
            "account_id": "BT_GATEWAY_ACCOUNT_ID",
            "exchange_type": "BT_GATEWAY_EXCHANGE_TYPE",
            "asset_type": "BT_GATEWAY_ASSET_TYPE",
            "gateway_startup_timeout_sec": "BT_GATEWAY_STARTUP_TIMEOUT_SEC",
            "gateway_command_timeout_sec": "BT_GATEWAY_COMMAND_TIMEOUT_SEC",
        }
        for key, env_name in env_map.items():
            value = os.environ.get(env_name)
            if value and key not in self._api_kwargs:
                self._api_kwargs[key] = value
        raw = os.environ.get("BT_GATEWAY_START_LOCAL_RUNTIME")
        if raw is not None:
            self._api_kwargs["gateway_start_local_runtime"] = raw not in {"0", "false", "False"}

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
        if not self._connected and not self._started:
            return

        if self._connected:
            self.emit_runtime_event("store_disconnect_requested", status="disconnecting")

        if self._api is not None:
            if hasattr(self._api, "disconnect"):
                self._api.disconnect()
            elif hasattr(self._api, "stop"):
                self._api.stop()

        self._connected = False
        self._started = False
        self._subscribed_datanames.clear()
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

    def supports_position_mode(self, mode: str) -> bool:
        """Return whether the configured provider advertises a position mode."""
        mode = str(mode or "net").strip().lower()
        if mode != "dual_side":
            return True

        if self._api is not None and hasattr(self._api, "supports_position_mode"):
            try:
                return bool(self._api.supports_position_mode(mode))
            except Exception:
                return False

        return bool(
            self._config.get("supports_dual_side")
            or str(self._config.get("position_mode", "")).strip().lower() == "dual_side"
            or self._api_kwargs.get("supports_dual_side")
            or str(self._api_kwargs.get("position_mode", "")).strip().lower() == "dual_side"
        )

    def get_balance(self):
        """Refresh cached cash and value from the API, if available."""
        if self._is_cache_fresh(self._last_balance_refresh, self._account_cache_ttl):
            return {"cash": self._cash, "value": self._value}

        api = self._ensure_api_ready()

        try:
            if hasattr(api, "get_balance"):
                balance = api.get_balance()
            elif hasattr(api, "get_account"):
                balance = api.get_account()
            else:
                return {"cash": self._cash, "value": self._value}
        except Exception:
            if self._last_balance_refresh > 0.0:
                return {"cash": self._cash, "value": self._value}
            raise

        if isinstance(balance, dict):
            self._cash = _coerce_float(
                balance.get("cash", balance.get("available", balance.get("balance"))),
                self._cash,
            )
            self._value = _coerce_float(
                balance.get("value", balance.get("equity", balance.get("total"))),
                self._value,
            )
            self._last_balance_refresh = time.monotonic()
            return {"cash": self._cash, "value": self._value}

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
        if self._is_cache_fresh(self._last_positions_refresh, self._positions_cache_ttl):
            return deepcopy(self._positions_cache)

        api = self._ensure_api_ready()

        try:
            if hasattr(api, "get_positions"):
                positions = api.get_positions()
            else:
                positions = []
        except AttributeError:
            positions = []
        except Exception:
            if self._last_positions_refresh > 0.0:
                return deepcopy(self._positions_cache)
            raise

        self._positions_cache = list(positions or [])
        self._last_positions_refresh = time.monotonic()

        return deepcopy(self._positions_cache)

    def getpositions(self) -> List[Dict[str, Any]]:
        """Alias for get_positions()."""
        return self.get_positions()

    @staticmethod
    def _is_cache_fresh(last_refresh: float, ttl: float) -> bool:
        if ttl <= 0.0 or last_refresh <= 0.0:
            return False
        return (time.monotonic() - last_refresh) < ttl

    def register(self, feed):
        """Register a feed instance with this store."""
        if feed not in self._data_feeds:
            self._data_feeds.append(feed)

    def subscribe(self, dataname: str):
        """Subscribe to market data for the given symbol."""
        api = self._ensure_api_ready()
        dataname = str(dataname)

        if dataname in self._subscribed_datanames:
            return

        if hasattr(api, "subscribe"):
            api.subscribe(dataname)
            self._subscribed_datanames.add(dataname)
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
        request_key = self._history_request_key(dataname, timeframe, compression, since, limit)
        if self._is_default_history_request(timeframe, compression, since, limit) and self._historical_bars[dataname]:
            return deepcopy(list(self._historical_bars[dataname]))
        if request_key in self._historical_query_cache:
            return deepcopy(self._historical_query_cache[request_key])

        api = self._ensure_api_ready()
        bars = []
        has_history_api = False

        if hasattr(api, "fetch_bars"):
            has_history_api = True
            bars = api.fetch_bars(
                dataname,
                timeframe=timeframe,
                compression=compression,
                since=since,
                limit=limit,
            )
        elif hasattr(api, "fetch_ohlcv"):
            has_history_api = True
            bars = api.fetch_ohlcv(
                dataname,
                timeframe=timeframe,
                compression=compression,
                since=since,
                limit=limit,
            )

        if not has_history_api and self._historical_bars[dataname]:
            return deepcopy(list(self._historical_bars[dataname]))

        normalized = [_normalize_bar(bar) for bar in bars or []]
        if self._is_default_history_request(timeframe, compression, since, limit):
            self._historical_bars[dataname].clear()
            self._historical_bars[dataname].extend(normalized)
        else:
            self._historical_query_cache[request_key] = list(normalized)
        return deepcopy(normalized)

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """Fetch the provider's currently open orders, if supported."""
        if self._is_cache_fresh(self._last_open_orders_refresh, self._open_orders_cache_ttl):
            return deepcopy(self._open_orders_cache)

        api = self._ensure_api_ready()

        try:
            if hasattr(api, "fetch_open_orders"):
                orders = api.fetch_open_orders()
            elif hasattr(api, "get_open_orders"):
                orders = api.get_open_orders()
            else:
                orders = []
        except AttributeError:
            orders = []
        except Exception:
            if self._last_open_orders_refresh > 0.0:
                return deepcopy(self._open_orders_cache)
            raise

        self._open_orders_cache = list(orders or [])
        self._last_open_orders_refresh = time.monotonic()
        return deepcopy(self._open_orders_cache)

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Alias for fetch_open_orders()."""
        return self.fetch_open_orders()

    def getopenorders(self) -> List[Dict[str, Any]]:
        """Compatibility alias for fetch_open_orders()."""
        return self.fetch_open_orders()

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

    def poll_orderbook(self, dataname: str):
        """Poll a single live orderbook snapshot from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if hasattr(api, "poll_orderbook"):
            return api.poll_orderbook(dataname)
        if hasattr(api, "get_next_orderbook"):
            return api.get_next_orderbook(dataname)
        return None

    def has_pending_tick(self, dataname: str) -> bool:
        """Return whether the API has queued live ticks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "has_pending_tick"):
            return bool(api.has_pending_tick(dataname))

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return bool(live_ticks.get(dataname))

        return False

    def has_pending_orderbook(self, dataname: str) -> bool:
        """Return whether the API has queued live orderbooks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "has_pending_orderbook"):
            return bool(api.has_pending_orderbook(dataname))

        live_orderbooks = getattr(api, "live_orderbooks", None)
        if live_orderbooks is not None:
            return bool(live_orderbooks.get(dataname))

        return False

    def supports_live_ticks(self, dataname: str) -> bool:
        """Return whether a symbol is configured for live tick streaming."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "supports_live_ticks"):
            return bool(api.supports_live_ticks(dataname))

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return dataname in live_ticks

        return False

    def supports_live_orderbook(self, dataname: str) -> bool:
        """Return whether a symbol is configured for live orderbook streaming."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if hasattr(api, "supports_live_orderbook"):
            return bool(api.supports_live_orderbook(dataname))

        live_orderbooks = getattr(api, "live_orderbooks", None)
        if live_orderbooks is not None:
            return dataname in live_orderbooks

        return False

    def poll_broker_update(self):
        """Poll a normalized broker-side order/trade/error update from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if not hasattr(api, "poll_broker_update"):
            return None

        update = api.poll_broker_update()
        if update is None:
            return None

        self._emit_broker_runtime_event(update)
        return update

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
        order_ref = (
            getattr(order.info, "external_order_id", None)
            or getattr(order.info, "ctp_order_ref", None)
            or getattr(order, "ref", None)
        )
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
        self._clear_history_query_cache(dataname)
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

    @staticmethod
    def _is_default_history_request(timeframe, compression, since, limit) -> bool:
        return timeframe is None and int(compression or 1) == 1 and since is None and limit is None

    @staticmethod
    def _history_request_key(dataname, timeframe, compression, since, limit):
        return (
            str(dataname),
            repr(timeframe),
            int(compression or 1),
            repr(since),
            None if limit is None else int(limit),
        )

    def _clear_history_query_cache(self, dataname: str) -> None:
        key_prefix = str(dataname)
        for key in [cache_key for cache_key in self._historical_query_cache if cache_key[0] == key_prefix]:
            self._historical_query_cache.pop(key, None)

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
        if self._successful_connect_count > 0:
            self.emit_runtime_event("store_reconnect_success", status="connected")
        self._successful_connect_count += 1
        self.emit_runtime_event("store_connected", status="connected")
        self.emit_runtime_event("store_ready", status="ready")
        if str(self.provider).lower() == "ctp" or _is_gateway_provider(self.provider):
            self.emit_runtime_event("store_auth_success", status="ready")
            self.emit_runtime_event("store_login_success", status="ready")
        self.get_balance()
        return self._api

    def _order_to_payload(self, order) -> Dict[str, Any]:
        """Convert a backtrader order into a generic bt_api_py payload."""
        from ..order import OrderBase

        order_type_str = order.getordername().lower()
        if getattr(order, "exectype", None) == OrderBase.Market or order_type_str == "market":
            price = None
        else:
            price = order.price if order.price is not None else order.created.price
            if price is not None and float(price) <= 0:
                price = order.created.price if order.created.price is not None else None
        data_name = self._extract_dataname(order.data)
        payload = {
            "symbol": data_name,
            "data_name": data_name,
            "bt_order_ref": getattr(order, "ref", None),
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(order.size),
            "price": price,
            "order_type": order_type_str,
            "valid": order.valid,
            "tradeid": getattr(order, "tradeid", 0),
        }

        if order.pricelimit is not None:
            payload["pricelimit"] = order.pricelimit

        offset = getattr(getattr(order, "info", {}), "get", lambda *_args, **_kwargs: None)("offset")
        if offset:
            payload["offset"] = offset

        position_side = getattr(getattr(order, "info", {}), "get", lambda *_args, **_kwargs: None)(
            "position_side"
        )
        if position_side:
            payload["position_side"] = position_side

        exchange_id = getattr(getattr(order, "info", {}), "get", lambda *_args, **_kwargs: None)(
            "exchange_id"
        )
        if exchange_id:
            payload["exchange_id"] = exchange_id

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

    def _emit_broker_runtime_event(self, update: Dict[str, Any]):
        """Translate normalized broker updates into runtime notifications."""
        kind = str(update.get("kind") or "").lower()
        details = {
            "data_name": update.get("data_name"),
            "side": update.get("side"),
            "offset": update.get("offset"),
            "size": update.get("size"),
            "price": update.get("price"),
            "trade_id": update.get("trade_id"),
            "exchange_id": update.get("exchange_id"),
        }
        details.update(dict(update.get("details") or {}))

        if kind == "order":
            status = str(update.get("status") or "submitted")
            event_type = {
                "submitted": "order_status_submitted",
                "accepted": "order_status_accepted",
                "partial": "order_status_partial",
                "completed": "order_status_completed",
                "canceled": "order_status_canceled",
                "rejected": "order_reject_remote",
            }.get(status, "order_status_update")
            level = "ERROR" if status == "rejected" else "INFO"
            self.emit_runtime_event(
                event_type,
                level=level,
                status=status,
                order_ref=update.get("external_order_id") or update.get("order_ref"),
                error_msg=str(update.get("status_msg") or ""),
                details=details,
            )
            return

        if kind == "trade":
            self.emit_runtime_event(
                "trade_execution",
                status="completed",
                order_ref=update.get("external_order_id") or update.get("order_ref"),
                details=details,
            )
            return

        if kind == "error":
            self.emit_runtime_event(
                "store_error",
                level="ERROR",
                status="error",
                error_code=str(update.get("error_code") or ""),
                error_msg=str(update.get("error_msg") or ""),
                details=details,
            )
