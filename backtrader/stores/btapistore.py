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
import math
import os
import re
import time
import uuid
import warnings
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple, cast

from ..events import TickEvent
from ..utils.log_message import get_logger
from .livestore import LiveStoreBase

logger = get_logger(__name__)


_PLACEHOLDER_PROVIDERS = frozenset({"futu", "oanda", "vc"})
_GATEWAY_PROVIDERS = frozenset({"gateway", "ctp_gateway", "mt5_gateway"})
_BACKENDS = frozenset({"direct", "gateway", "forwarding"})
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
_UTC = _dt.timezone.utc
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
    "2": "canceled",
    "3": "accepted",
    "4": "canceled",
    "5": "canceled",
    "a": "submitted",
    "b": "submitted",
    "c": "submitted",
}
_CTP_ORDER_SUBMIT_STATUS_MAP = {
    "4": "rejected",
    "5": "cancel_rejected",
    "6": "rejected",
}


def _normalize_ctp_order_status(
    order_status: Any,
    submit_status: Any = None,
    default: str = "submitted",
) -> str:
    """Normalize CTP order status, letting explicit submit rejections win."""
    status = _CTP_ORDER_STATUS_MAP.get(_ctp_code(order_status, "a"), default)
    submit_override = _CTP_ORDER_SUBMIT_STATUS_MAP.get(_ctp_code(submit_status, ""))
    return submit_override or status

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
    if isinstance(value, dict):
        for key in ("amount", "value", "balance", "total"):
            if key in value and value[key] not in (None, ""):
                return _coerce_float(value[key], default)
        return default
    if isinstance(value, str):
        value = value.strip().replace(",", "")

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _normalise_ctp_commission_rate(value: Any, default: float = 0.0) -> float:
    """Normalize CTP by-money commission to a decimal rate."""
    rate = _coerce_float(value, default)
    if rate > 0.01:
        return rate / 10000.0
    return max(rate, 0.0)


def _first_float(mapping: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    """Return the first finite numeric value from a mapping."""
    for key in keys:
        if key not in mapping:
            continue
        number = _coerce_float(mapping[key], None)
        if number is not None:
            return number
    return None


_ACCOUNT_CASH_KEYS = (
    "cash",
    "available_cash",
    "available",
    "Available",
    "available_funds",
    "AvailableFunds",
    "availablefunds",
    "available_balance",
    "availableBalance",
    "available_bal",
    "availableBal",
    "available_equity",
    "availableEquity",
    "avail_eq",
    "availEq",
    "avail_bal",
    "availBal",
    "total_available_balance",
    "totalAvailableBalance",
    "total_available_margin",
    "totalAvailableMargin",
    "free_collateral",
    "freeCollateral",
    "free_margin",
    "freeMargin",
    "marginFree",
    "margin_free",
    "withdraw_available",
    "withdrawAvailable",
    "available_to_withdraw",
    "availableToWithdraw",
)

_ACCOUNT_VALUE_KEYS = (
    "value",
    "equity",
    "Equity",
    "eq",
    "total_eq",
    "totalEq",
    "total_equity",
    "totalEquity",
    "account_value",
    "accountValue",
    "net_liquidation",
    "NetLiquidation",
    "netliquidation",
    "NetLiquidationValue",
    "total_margin",
    "totalMargin",
    "total_margin_balance",
    "totalMarginBalance",
    "margin_balance",
    "marginBalance",
    "total_wallet_balance",
    "totalWalletBalance",
    "wallet_balance",
    "walletBalance",
    "balance",
    "Balance",
    "total",
)

_ACCOUNT_MARGIN_KEYS = (
    "margin",
    "used_margin",
    "usedMargin",
    "margin_used",
    "marginUsed",
    "curr_margin",
    "CurrMargin",
    "initial_margin",
    "initialMargin",
    "initial_margin_requirement",
    "initialMarginRequirement",
    "total_initial_margin",
    "totalInitialMargin",
    "total_used_margin",
    "totalUsedMargin",
    "total_position_initial_margin",
    "totalPositionInitialMargin",
    "total_open_order_initial_margin",
    "totalOpenOrderInitialMargin",
    "imr",
    "maintain_margin",
    "maintenance_margin",
    "maintMargin",
)

_ACCOUNT_WRAPPER_KEYS = (
    "account",
    "accounts",
    "balance",
    "wallet",
    "data",
    "result",
    "list",
    "items",
    "rows",
    "payload",
)


def _materialize_account_payload(raw: Any) -> Any:
    for method_name in ("get_all_data", "get_data"):
        method = getattr(raw, method_name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                return raw
    return raw


def _account_error_message(row: Dict[str, Any]) -> Optional[str]:
    status = str(row.get("status") or "").strip().lower()
    if status == "error":
        return str(row.get("message") or row.get("error") or "account query failed")

    if "retCode" in row:
        ret_code = str(row.get("retCode") or "").strip()
        if ret_code and ret_code != "0":
            return str(
                row.get("retMsg")
                or row.get("message")
                or row.get("error")
                or f"account query failed: retCode={ret_code}"
            )

    if "code" in row and any(key in row for key in ("msg", "message", "data")):
        code = str(row.get("code") or "").strip()
        if code and code not in {"0", "200", "00000"}:
            return str(
                row.get("msg")
                or row.get("message")
                or row.get("error")
                or f"account query failed: code={code}"
            )

    return None


def _account_payload_candidates(raw: Any, *, depth: int = 0) -> List[Dict[str, Any]]:
    if depth > 8:
        return []

    raw = _materialize_account_payload(raw)
    if isinstance(raw, dict):
        message = _account_error_message(raw)
        if message:
            raise RuntimeError(message)

        candidates = [raw]
        for key in _ACCOUNT_WRAPPER_KEYS:
            if key not in raw:
                continue
            value = raw.get(key)
            if key == "accounts" and isinstance(value, dict):
                for item in value.values():
                    candidates.extend(_account_payload_candidates(item, depth=depth + 1))
            else:
                candidates.extend(_account_payload_candidates(value, depth=depth + 1))
        return candidates

    if isinstance(raw, (list, tuple)):
        candidates: List[Dict[str, Any]] = []
        for item in raw:
            candidates.extend(_account_payload_candidates(item, depth=depth + 1))
        return candidates

    return []


def _normalise_account_balance_payload(raw: Any) -> Optional[Tuple[float | None, float | None]]:
    for payload in _account_payload_candidates(raw):
        cash = _first_float(payload, _ACCOUNT_CASH_KEYS)
        value = _first_float(payload, _ACCOUNT_VALUE_KEYS)
        margin = _first_float(payload, _ACCOUNT_MARGIN_KEYS)
        if cash is None and value is None and margin is None:
            continue
        if cash is None and value is not None and margin is not None:
            cash = value - margin
        if cash is None:
            cash = _first_float(payload, ("balance", "Balance"))
        if value is None:
            value = _first_float(payload, ("balance", "Balance"))
        return cash, value if value is not None else cash
    return None


def _coerce_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with a stable fallback."""
    if value is None:
        return default

    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError):
            return default
        if not number.is_finite() or number != number.to_integral_value():
            return default
        return int(number)

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


def _ctp_code(value: Any, default: str = "") -> str:
    """Normalize CTP enum-like fields that may arrive as numeric strings."""
    if value is None:
        return default
    text = _coerce_text(value, default="")
    if text == "":
        return default
    text = text.replace(",", "")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if not number.is_finite():
        return default
    if number == number.to_integral_value():
        return str(int(number))
    return text


def _ctp_direction(value: Any, default: str = "buy") -> str:
    """Normalize CTP buy/sell direction flags."""
    code = _ctp_code(value, "")
    direction = _CTP_DIRECTION_MAP.get(code)
    if direction is not None:
        return direction
    text = code.lower().replace("-", "_")
    if text in {"buy", "long", "b"}:
        return "buy"
    if text in {"sell", "short", "s"}:
        return "sell"
    return default


def _ctp_offset(value: Any, default: str = "open") -> str:
    """Normalize CTP offset flags."""
    code = _ctp_code(value, "")
    offset = _CTP_OFFSET_MAP.get(code) or _CTP_OFFSET_MAP.get(code[:1])
    if offset is not None:
        return offset
    text = code.lower().replace("-", "_")
    if text in _CTP_OFFSET_FLAG:
        return text
    return default


def _ctp_position_direction(value: Any, default: str = "long") -> str:
    """Normalize CTP position direction flags."""
    code = _ctp_code(value, "")
    text = code.lower().replace("-", "_")
    if text in {"3", "short", "sell", "s"}:
        return "short"
    if text in {"2", "long", "buy", "b"}:
        return "long"
    return default


def _safe_field_attr(obj: Any, attr: str, default: Any = None) -> Any:
    """Read an attribute from a SWIG field or a pre-snapshotted dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)

    try:
        return getattr(obj, attr, default)
    except Exception as e:
        logger.debug("Failed to get attr %s from %s: %s", attr, type(obj).__name__, e)
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
            value = _safe_field_attr(obj, attr)
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
        left, right = text.split(".", 1)
        left_text = left.strip()
        right_text = right.strip()
        left_exchange = left_text.upper()
        right_exchange = right_text.upper()
        if left_exchange in _CTP_EXCHANGES:
            return _normalize_ctp_instrument(right_text, left_exchange), left_exchange
        if right_exchange in _CTP_EXCHANGES:
            return _normalize_ctp_instrument(left_text, right_exchange), right_exchange
        return _normalize_ctp_instrument(left_text, right_exchange), right_exchange

    if "_" in text:
        left, right = text.split("_", 1)
        left_text = left.strip()
        right_text = right.strip()
        left_exchange = left_text.upper()
        right_exchange = right_text.upper()
        if left_exchange in _CTP_EXCHANGES:
            return _normalize_ctp_instrument(right_text, left_exchange), left_exchange
        if right_exchange in _CTP_EXCHANGES:
            return _normalize_ctp_instrument(left_text, right_exchange), right_exchange

    return _normalize_ctp_instrument(text, ""), ""


def _contract_metadata_aliases(symbol: Any) -> List[str]:
    """Return symbol aliases used when matching configured contract metadata."""
    raw = _coerce_text(symbol)
    aliases = [raw]

    if "." in raw:
        head, tail = (part.strip() for part in raw.split(".", 1))
        head_upper = head.upper()
        tail_upper = tail.upper()
        if head_upper in _CTP_EXCHANGES:
            aliases.extend([tail, tail.upper(), tail.lower()])
        elif tail_upper in _CTP_EXCHANGES:
            aliases.extend([head, head.upper(), head.lower()])
        else:
            aliases.extend([tail, tail.upper(), tail.lower()])

    if "_" in raw:
        head, tail = (part.strip() for part in raw.split("_", 1))
        head_upper = head.upper()
        tail_upper = tail.upper()
        if head_upper in _CTP_EXCHANGES:
            aliases.extend([tail, tail.upper(), tail.lower()])
        elif tail_upper in _CTP_EXCHANGES:
            aliases.extend([head, head.upper(), head.lower()])

    aliases.extend([raw.upper(), raw.lower()])
    compact = "".join(ch for ch in raw if ch.isalnum())
    aliases.extend([compact, compact.upper(), compact.lower()])

    result = []
    seen = set()
    for alias in aliases:
        if alias and alias not in seen:
            result.append(alias)
            seen.add(alias)
    return result


_CONTRACT_METADATA_CONTAINER_KEYS = (
    "data",
    "result",
    "payload",
    "list",
    "rows",
    "items",
    "symbols",
    "instruments",
    "contracts",
    "markets",
)
_CONTRACT_METADATA_NESTED_KEYS = (
    "priceFilter",
    "price_filter",
    "lotSizeFilter",
    "lot_size_filter",
    "leverageFilter",
    "leverage_filter",
    "fee",
    "fees",
)


def _compact_contract_symbol(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", _coerce_text(value)).upper()


def _materialize_contract_payload(raw: Any) -> Any:
    for method_name in ("get_all_data", "get_data", "to_dict", "as_dict", "dict", "model_dump"):
        method = getattr(raw, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method()
        except Exception:
            continue
        if payload not in (None, "") and payload is not raw:
            return payload
    return raw


def _contract_payload_symbol_values(row: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in (
        "symbol",
        "data_name",
        "symbol_name",
        "instId",
        "instrument",
        "instrument_id",
        "InstrumentID",
        "REFERENCE_CODE",
        "localSymbol",
        "local_symbol",
        "pair",
        "id",
        "name",
        "contract",
        "contract_code",
        "contractCode",
    ):
        value = row.get(key)
        if value not in (None, ""):
            values.append(_coerce_text(value))
    return values


def _contract_payload_matches_symbol(row: Dict[str, Any], symbol: Any) -> bool:
    text = _coerce_text(symbol)
    if not text:
        return True
    aliases = _contract_metadata_aliases(text)
    candidates = {_coerce_text(alias).upper() for alias in aliases if _coerce_text(alias)}
    candidates.update(_compact_contract_symbol(alias) for alias in aliases if _coerce_text(alias))
    for value in _contract_payload_symbol_values(row):
        if value.upper() in candidates or _compact_contract_symbol(value) in candidates:
            return True
    return False


def _select_contract_payload_row(payload: Any, symbol: Any) -> Optional[Dict[str, Any]]:
    payload = _materialize_contract_payload(payload)
    if not isinstance(payload, (list, tuple, set)):
        return None
    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        return None
    if symbol:
        for row in rows:
            if _contract_payload_matches_symbol(row, symbol):
                return row
        if len(rows) > 1:
            return None
    return rows[0]


def _flatten_contract_metadata_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    flattened = dict(data)
    for key in _CONTRACT_METADATA_NESTED_KEYS:
        nested = flattened.get(key)
        if isinstance(nested, dict):
            for nested_key, nested_value in nested.items():
                flattened.setdefault(str(nested_key), nested_value)

    filters = flattened.get("filters")
    if isinstance(filters, (list, tuple, set)):
        for item in filters:
            if not isinstance(item, dict):
                continue
            filter_type = _coerce_text(item.get("filterType") or item.get("filter_type"))
            for nested_key, nested_value in item.items():
                if nested_key in {"filterType", "filter_type"}:
                    continue
                flattened.setdefault(str(nested_key), nested_value)
                if filter_type:
                    flattened.setdefault(f"{filter_type}_{nested_key}", nested_value)
    return flattened


def _unwrap_contract_metadata_payload(raw: Any, symbol: Any) -> Dict[str, Any]:
    raw = _materialize_contract_payload(raw)
    if isinstance(raw, (list, tuple, set)):
        row = _select_contract_payload_row(raw, symbol)
        return dict(row or {})
    if not isinstance(raw, dict):
        return {}

    data = dict(raw)
    for _ in range(10):
        for key in _CONTRACT_METADATA_CONTAINER_KEYS:
            payload = data.get(key)
            row: Optional[Dict[str, Any]]
            if isinstance(payload, dict):
                row = payload
            else:
                row = _select_contract_payload_row(payload, symbol)
            if row is None:
                continue
            base = {item_key: item_value for item_key, item_value in data.items() if item_key != key}
            base.update(row)
            if base == data:
                return _flatten_contract_metadata_payload(data)
            data = base
            break
        else:
            break
    return _flatten_contract_metadata_payload(data)


def _normalise_exchange_commission_rate(
    key: str,
    value: Any,
    *,
    okx_fee_sign: bool = False,
) -> Optional[float]:
    number = _coerce_float(value, None)
    if number is None:
        return None
    key_lower = key.strip().lower()
    if key_lower in {"makercommission", "takercommission"} and abs(number) > 1:
        return number / 10000.0
    if key_lower in {"makercommissionrate", "takercommissionrate"} and abs(number) > 1:
        return number / 10000.0
    if key_lower in {"makeru", "takeru"} or (
        okx_fee_sign and key_lower in {"maker", "taker"}
    ):
        return -number
    if abs(number) > 1:
        return number / 100.0
    return number


def _first_metadata_item(metadata: Dict[str, Any], *keys: str) -> Tuple[str, Any]:
    for key in keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if value in (None, ""):
            continue
        return key, value
    return "", None


def _normalise_contract_metadata(raw: Any, symbol: Any, *, source: str = "") -> Dict[str, Any]:
    data = _unwrap_contract_metadata_payload(raw, symbol)
    if not data:
        return {}

    metadata = dict(data)
    symbol_text = _coerce_text(
        symbol
        or data.get("symbol")
        or data.get("data_name")
        or data.get("instId")
        or data.get("instrument")
        or data.get("InstrumentID")
    )
    if symbol_text:
        metadata["symbol"] = symbol_text
    if source:
        metadata["source"] = source

    aliases = {
        "category": ("asset_type", "instType"),
        "contractType": ("contract_type",),
        "baseCoin": ("base_asset", "baseCcy"),
        "quoteCoin": ("quote_asset", "quoteCcy"),
        "settleCoin": ("settle_currency", "settleCcy"),
        "tickSize": ("price_tick", "tick_size", "min_price_tick"),
        "minOrderQty": ("min_order_size", "min_order_qty"),
        "maxOrderQty": ("max_order_size", "max_order_qty"),
        "maxMktOrderQty": ("market_max_order_size", "max_market_order_size"),
        "maxMarketOrderQty": ("market_max_order_size", "max_market_order_size"),
        "qtyStep": ("order_size_step", "qty_step"),
        "stepSize": ("order_size_step", "qty_step"),
        "maxLeverage": ("max_leverage",),
    }
    for src_key, target_keys in aliases.items():
        value = data.get(src_key)
        if value in (None, ""):
            continue
        for target_key in target_keys:
            metadata.setdefault(target_key, value)

    asset_type = _coerce_text(metadata.get("asset_type") or metadata.get("instType"))
    contract_type = _coerce_text(metadata.get("contract_type") or metadata.get("contractType"))
    if (
        metadata.get("multiplier") in (None, "")
        and metadata.get("contract_size") in (None, "")
        and "linear" in f"{asset_type} {contract_type}".lower()
    ):
        metadata["multiplier"] = 1.0
        metadata["contract_size"] = 1.0

    okx_fee_sign = "okx" in " ".join(
        str(metadata.get(key) or "")
        for key in ("source", "fee_source", "exchange", "exchange_id")
    ).lower() or any(
        key in metadata
        for key in (
            "makerU",
            "takerU",
            "makerUSDC",
            "takerUSDC",
            "feeGroup",
        )
    )
    maker_key, maker_value = _first_metadata_item(
        metadata,
        "maker_commission_rate",
        "maker_fee_rate",
        "makerCommissionRate",
        "makerCommission",
        "makerU",
        "maker",
    )
    taker_key, taker_value = _first_metadata_item(
        metadata,
        "taker_commission_rate",
        "taker_fee_rate",
        "takerCommissionRate",
        "takerCommission",
        "takerU",
        "taker",
    )
    maker_rate = _normalise_exchange_commission_rate(
        maker_key,
        maker_value,
        okx_fee_sign=okx_fee_sign,
    )
    taker_rate = _normalise_exchange_commission_rate(
        taker_key,
        taker_value,
        okx_fee_sign=okx_fee_sign,
    )
    if maker_rate is not None:
        metadata["maker_commission_rate"] = maker_rate
    if taker_rate is not None:
        metadata["taker_commission_rate"] = taker_rate
        metadata.setdefault("commission_rate", taker_rate)
        metadata.setdefault("open_commission_rate", taker_rate)

    return {key: value for key, value in metadata.items() if value not in (None, "")}


_CONTRACT_METADATA_RULE_KEYS = (
    "multiplier",
    "mult",
    "contract_multiplier",
    "contract_size",
    "contract_value",
    "contractValue",
    "ctVal",
    "ctMult",
    "VolumeMultiple",
    "margin",
    "margin_rate",
    "margin_ratio",
    "max_leverage",
    "leverage",
    "lever",
    "commission_rate",
    "open_commission_rate",
    "close_commission_rate",
    "close_today_commission_rate",
    "maker_commission_rate",
    "taker_commission_rate",
    "commission_amount",
    "open_commission_amount",
    "close_commission_amount",
    "min_price_tick",
    "price_tick",
    "tick_size",
    "min_order_size",
    "max_order_size",
    "order_size_step",
    "asset_type",
    "instType",
    "contract_type",
    "contractType",
)


def _contract_metadata_has_rules(metadata: Dict[str, Any]) -> bool:
    return any(metadata.get(key) not in (None, "") for key in _CONTRACT_METADATA_RULE_KEYS)


def _contract_metadata_method_attempts(
    api: Any,
    method_name: str,
    query_symbol: str,
    *,
    include_empty_call: bool = False,
) -> List[Tuple[Tuple[Any, ...], Dict[str, Any]]]:
    asset_type = _coerce_text(getattr(api, "asset_type", ""))
    instrument_method = method_name in {
        "get_instruments",
        "fetch_instruments",
        "get_public_instruments",
        "fetch_public_instruments",
    }
    attempts: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    if query_symbol:
        if instrument_method and asset_type:
            attempts.append(((), {"asset_type": asset_type, "inst_id": query_symbol}))
        if instrument_method:
            attempts.extend(
                (
                    ((), {"inst_id": query_symbol}),
                    ((), {"instId": query_symbol}),
                    ((), {"instrument": query_symbol}),
                )
            )
        attempts.extend(
            (
                ((query_symbol,), {}),
                ((), {"symbol": query_symbol}),
                ((), {"inst_id": query_symbol}),
                ((), {"instId": query_symbol}),
                ((), {"instrument": query_symbol}),
            )
        )
    if include_empty_call:
        if instrument_method and asset_type:
            attempts.append(((), {"asset_type": asset_type}))
        attempts.append(((), {}))

    result: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    seen = set()
    for args, kwargs in attempts:
        marker = repr((args, sorted(kwargs.items())))
        if marker in seen:
            continue
        seen.add(marker)
        result.append((args, kwargs))
    return result


def _query_contract_fee_metadata(api: Any, aliases: List[str], symbol: Any) -> Dict[str, Any]:
    for method_name in (
        "get_fee",
        "fetch_fee",
        "get_fee_rate",
        "fetch_fee_rate",
        "get_commission_rate",
        "fetch_commission_rate",
    ):
        method = getattr(api, method_name, None)
        if not callable(method):
            continue
        for query_symbol in aliases:
            try:
                payload = method(query_symbol)
            except Exception:
                continue
            metadata = _normalise_contract_metadata(payload, symbol, source=method_name)
            if any(
                metadata.get(key) not in (None, "")
                for key in (
                    "commission_rate",
                    "maker_commission_rate",
                    "taker_commission_rate",
                    "commission_amount",
                )
            ):
                return metadata
    return {}


def _query_contract_metadata_from_api(api: Any, aliases: List[str], symbol: Any) -> Dict[str, Any]:
    fee_metadata = _query_contract_fee_metadata(api, aliases, symbol)
    for method_name in (
        "get_symbol_info",
        "fetch_symbol_info",
        "get_exchange_info",
        "fetch_exchange_info",
        "get_instruments",
        "fetch_instruments",
        "get_public_instruments",
        "fetch_public_instruments",
        "get_contract",
        "fetch_contract",
        "query_symbol",
        "get_market",
        "fetch_market",
    ):
        method = getattr(api, method_name, None)
        if not callable(method):
            continue
        attempts: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
        for query_symbol in aliases:
            attempts.extend(_contract_metadata_method_attempts(api, method_name, query_symbol))
        attempts.extend(
            _contract_metadata_method_attempts(
                api,
                method_name,
                "",
                include_empty_call=True,
            )
        )
        for args, kwargs in attempts:
            try:
                payload = method(*args, **kwargs)
            except Exception:
                continue
            metadata = _normalise_contract_metadata(payload, symbol, source=method_name)
            if not _contract_metadata_has_rules(metadata):
                continue
            if fee_metadata:
                fee_source = fee_metadata.get("source")
                metadata.update({key: value for key, value in fee_metadata.items() if key != "source"})
                if fee_source:
                    metadata["fee_source"] = fee_source
            return metadata
    return fee_metadata


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


def _positive_int_lot(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or value in (None, ""):
        raise BtApiStoreError(f"CTP order {field_name} must be a positive integer lot")
    try:
        lot = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise BtApiStoreError(f"CTP order {field_name} must be a positive integer lot") from exc
    if not lot.is_finite() or lot <= 0 or lot != lot.to_integral_value():
        raise BtApiStoreError(f"CTP order {field_name} must be a positive integer lot")
    return int(lot)


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
        dt_value = bar.get("timestamp")
        if dt_value in (None, ""):
            dt_value = bar.get("datetime") or bar.get("dt") or bar.get("time")
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


def _datetime_to_utc_naive(value: _dt.datetime) -> _dt.datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(_UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def _normalize_datetime(value: Any) -> _dt.datetime:
    """Normalize timestamps to naive UTC datetimes."""
    if isinstance(value, _dt.datetime):
        return _datetime_to_utc_naive(value)

    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return _dt.datetime.fromtimestamp(ts, _UTC).replace(tzinfo=None)

    if isinstance(value, str):
        try:
            return _datetime_to_utc_naive(_dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
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

    raise BtApiMissingDependencyError(
        "bt_api_py is installed but no supported client class was found"
    )


def _create_ctp_wrapper_class():
    """Create a wrapper class for CTP clients."""
    try:
        import bt_api_ctp.ctp.client as ctp_client_module
        from bt_api_ctp.ctp.client import MdClient, TraderClient
        from bt_api_ctp.ctp.ctp_md_api import CThostFtdcMdSpi
        from bt_api_ctp.ctp.ctp_structs_order import (
            CThostFtdcInputOrderActionField,
            CThostFtdcInputOrderField,
        )
        from bt_api_ctp.ctp.ctp_trader_api import CThostFtdcTraderSpi
    except ImportError:
        try:
            import bt_api_py.ctp.client as ctp_client_module
            from bt_api_py.ctp.client import MdClient, TraderClient
            from bt_api_py.ctp.ctp_md_api import CThostFtdcMdSpi
            from bt_api_py.ctp.ctp_structs_order import (
                CThostFtdcInputOrderActionField,
                CThostFtdcInputOrderField,
            )
            from bt_api_py.ctp.ctp_trader_api import CThostFtdcTraderSpi
        except ImportError as fallback_exc:
            raise BtApiMissingDependencyError("CTP support is not available") from fallback_exc

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
            """Initialize the CTP client wrapper.

            Args:
                **kwargs: Configuration parameters including:
                    - md_address/md_front: Market data server address
                    - td_address/td_front: Trading server address
                    - broker_id: Broker identifier
                    - investor_id/user_id: Investor identifier
                    - password: Account password
                    - app_id: Application identifier (default: simnow_client_test)
                    - auth_code: Authentication code (default: 0000000000000000)
            """
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
            self._symbol_specs = {}
            self._order_updates: collections.deque = collections.deque()
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
                state = self.get_session_state()
                auth_state = str(state.get("auth_state") or "").lower()
                login_state = str(state.get("login_state") or "").lower()
                last_auth_error = state.get("last_auth_error") or {}
                last_login_error = state.get("last_login_error") or {}
                if auth_state == "failed":
                    msg = str(last_auth_error.get("error_msg") or "authentication failed")
                    raise BtApiStoreError(f"CTP authentication failed: {msg}")
                if login_state in {"blocked", "failed"}:
                    msg = str(last_login_error.get("error_msg") or "login failed")
                    raise BtApiStoreError(f"CTP trader login failed: {msg}")
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

        def get_session_state(self):
            """Return CTP trader auth/login state from the underlying client."""
            if self.trader_client and hasattr(self.trader_client, "get_session_state"):
                return self.trader_client.get_session_state()
            return {
                "connected": bool(self._connected),
                "ready": False,
                "auth_state": "unknown",
                "login_state": "unknown",
            }

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
                    available = _coerce_float(_safe_field_attr(account, "Available"))
                    balance = _coerce_float(
                        _safe_field_attr(account, "Balance"),
                        available,
                    )
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
            aggregated: dict = {}
            for row in rows or []:
                instrument = _safe_text_attr(row, "InstrumentID")
                if not instrument:
                    continue

                direction = _ctp_position_direction(_safe_field_attr(row, "PosiDirection", ""))
                key = (instrument, direction)
                exchange_id = _safe_text_attr(row, "ExchangeID")
                spec_symbol = f"{exchange_id}.{instrument}" if exchange_id else instrument
                spec = self.get_symbol_info(spec_symbol)
                multiplier = _coerce_float(spec.get("multiplier"), 1.0)
                if multiplier <= 0:
                    multiplier = 1.0

                volume = _coerce_float(_safe_field_attr(row, "Position"))
                if volume <= 0:
                    continue

                cost = _coerce_float(
                    _safe_field_attr(row, "PositionCost"),
                    _coerce_float(_safe_field_attr(row, "OpenCost")),
                )

                item = aggregated.setdefault(
                    key,
                    {
                        "instrument": instrument,
                        "symbol": instrument,
                        "direction": direction,
                        "exchange_id": exchange_id,
                        "volume": 0.0,
                        "cost": 0.0,
                        "open_cost": 0.0,
                        "use_margin": 0.0,
                        "position_profit": 0.0,
                        "close_profit": 0.0,
                        "commission": 0.0,
                        "today_position": 0.0,
                        "yd_position": 0.0,
                        "mark_price": _coerce_float(_safe_field_attr(row, "SettlementPrice")),
                        "spec": spec,
                    },
                )
                item["volume"] += volume
                item["cost"] += cost
                item["open_cost"] += _coerce_float(_safe_field_attr(row, "OpenCost"))
                item["use_margin"] += _coerce_float(_safe_field_attr(row, "UseMargin"))
                item["position_profit"] += _coerce_float(_safe_field_attr(row, "PositionProfit"))
                item["close_profit"] += _coerce_float(_safe_field_attr(row, "CloseProfit"))
                item["commission"] += _coerce_float(_safe_field_attr(row, "Commission"))
                item["today_position"] += _coerce_float(_safe_field_attr(row, "TodayPosition"))
                item["yd_position"] += _coerce_float(_safe_field_attr(row, "YdPosition"))

            self._positions_cache = []
            for item in aggregated.values():
                volume = item["volume"] or 0.0
                spec = item.get("spec") or {}
                multiplier = _coerce_float(spec.get("multiplier"), 1.0)
                denominator = volume * multiplier if multiplier > 0 else volume
                avg_price = (item["cost"] / denominator) if denominator else 0.0
                current_price = self._last_tick_price.get(item["instrument"]) or item.get(
                    "mark_price"
                )
                self._positions_cache.append(
                    {
                        "instrument": item["instrument"],
                        "symbol": item["symbol"],
                        "direction": item["direction"],
                        "exchange_id": item["exchange_id"],
                        "volume": volume,
                        "price": avg_price,
                        "avg_price": avg_price,
                        "current_price": current_price,
                        "mark_price": item.get("mark_price"),
                        "profit": item["position_profit"],
                        "position_profit": item["position_profit"],
                        "close_profit": item["close_profit"],
                        "commission": item["commission"],
                        "use_margin": item["use_margin"],
                        "margin_value": item["use_margin"],
                        "initial_margin": item["use_margin"],
                        "today_position": item["today_position"],
                        "yd_position": item["yd_position"],
                        "position_cost": item["cost"],
                        "open_cost": item["open_cost"],
                        **spec,
                    }
                )

            return list(self._positions_cache)

        def get_symbol_info(self, symbol):
            """Fetch and cache CTP contract specs, margin rates and commission rates."""
            instrument, exchange_id = _split_ctp_symbol(symbol)
            cache_keys = [key for key in (str(symbol or "").strip(), instrument) if key]
            for key in cache_keys:
                cached = self._symbol_specs.get(key)
                if cached:
                    return dict(cached)

            if not self.trader_client or not self.trader_client.is_ready or not instrument:
                return {}

            instrument_info = self._safe_trader_query(
                "query_instrument",
                instrument,
                exchange_id=exchange_id,
                timeout=5,
            )
            margin_info = self._safe_trader_query(
                "query_instrument_margin_rate",
                instrument,
                exchange_id=exchange_id,
                timeout=5,
            )
            commission_info = self._safe_trader_query(
                "query_instrument_commission_rate",
                instrument,
                exchange_id=exchange_id,
                timeout=5,
            )
            spec = self._build_symbol_spec(
                instrument,
                exchange_id,
                instrument_info,
                margin_info,
                commission_info,
            )
            if spec:
                for key in cache_keys + [spec.get("instrument", ""), spec.get("symbol", "")]:
                    if key:
                        self._symbol_specs[str(key)] = dict(spec)
            return spec

        def _safe_trader_query(self, method_name, *args, **kwargs):
            method = getattr(self.trader_client, method_name, None)
            if not callable(method):
                return None
            try:
                return method(*args, **kwargs)
            except TypeError:
                kwargs.pop("exchange_id", None)
                try:
                    return method(*args, **kwargs)
                except Exception as exc:
                    logger.debug("CTP %s failed: %s", method_name, exc)
                    return None
            except Exception as exc:
                logger.debug("CTP %s failed: %s", method_name, exc)
                return None

        @staticmethod
        def _build_symbol_spec(
            instrument,
            exchange_id,
            instrument_info,
            margin_info,
            commission_info,
        ):
            if not any((instrument_info, margin_info, commission_info)):
                return {}
            symbol = (
                _safe_text_attr(instrument_info, "InstrumentID")
                or _safe_text_attr(margin_info, "InstrumentID")
                or _safe_text_attr(commission_info, "InstrumentID")
                or str(instrument or "").strip()
            )
            exchange = (
                _safe_text_attr(instrument_info, "ExchangeID")
                or _safe_text_attr(margin_info, "ExchangeID")
                or _safe_text_attr(commission_info, "ExchangeID")
                or str(exchange_id or "").strip()
            )
            multiplier = _coerce_float(_safe_field_attr(instrument_info, "VolumeMultiple"), 0.0)
            price_tick = _coerce_float(_safe_field_attr(instrument_info, "PriceTick"), 0.0)
            long_margin_rate = _coerce_float(
                _safe_field_attr(margin_info, "LongMarginRatioByMoney"), 0.0
            )
            short_margin_rate = _coerce_float(
                _safe_field_attr(margin_info, "ShortMarginRatioByMoney"), 0.0
            )
            open_fee_rate = _normalise_ctp_commission_rate(
                _safe_field_attr(commission_info, "OpenRatioByMoney"), 0.0
            )
            open_fee_amount = _coerce_float(
                _safe_field_attr(commission_info, "OpenRatioByVolume"), 0.0
            )
            close_fee_rate = _normalise_ctp_commission_rate(
                _safe_field_attr(commission_info, "CloseRatioByMoney"), 0.0
            )
            close_fee_amount = _coerce_float(
                _safe_field_attr(commission_info, "CloseRatioByVolume"), 0.0
            )
            close_today_fee_rate = _normalise_ctp_commission_rate(
                _safe_field_attr(commission_info, "CloseTodayRatioByMoney"), 0.0
            )
            close_today_fee_amount = _coerce_float(
                _safe_field_attr(commission_info, "CloseTodayRatioByVolume"), 0.0
            )
            margin_rate = long_margin_rate or short_margin_rate or 0.0
            spec = {
                "source": "ctp_direct",
                "symbol": symbol,
                "instrument": symbol,
                "exchange": exchange,
                "exchange_id": exchange,
                "product_id": _safe_text_attr(instrument_info, "ProductID"),
                "price_tick": price_tick,
                "tick_size": price_tick,
                "multiplier": multiplier,
                "contract_multiplier": multiplier,
                "contract_size": multiplier,
                "volume_multiple": multiplier,
                "margin": margin_rate,
                "margin_rate": margin_rate,
                "long_margin_rate": long_margin_rate,
                "short_margin_rate": short_margin_rate,
                "long_margin_amount": _coerce_float(
                    _safe_field_attr(margin_info, "LongMarginRatioByVolume"), 0.0
                ),
                "short_margin_amount": _coerce_float(
                    _safe_field_attr(margin_info, "ShortMarginRatioByVolume"), 0.0
                ),
                "open_fee_rate": open_fee_rate,
                "open_commission_rate": open_fee_rate,
                "commission_rate": open_fee_rate,
                "open_fee_amount": open_fee_amount,
                "open_commission_amount": open_fee_amount,
                "commission_amount": open_fee_amount,
                "close_fee_rate": close_fee_rate,
                "close_commission_rate": close_fee_rate,
                "close_fee_amount": close_fee_amount,
                "close_commission_amount": close_fee_amount,
                "close_today_fee_rate": close_today_fee_rate,
                "close_today_commission_rate": close_today_fee_rate,
                "close_today_fee_amount": close_today_fee_amount,
                "close_today_commission_amount": close_today_fee_amount,
            }
            return {key: value for key, value in spec.items() if value not in (None, "", 0.0)}

        def fetch_bars(
            self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs
        ):
            """Fetch historical bars (not implemented for CTP live)."""
            # CTP live doesn't support historical data in basic mode
            return []

        def fetch_ohlcv(
            self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs
        ):
            """Fetch OHLCV data (not implemented for CTP live)."""
            # CTP live doesn't support historical data in basic mode
            return []

        def poll_bar(self, symbol):
            """Poll for next bar (not implemented)."""
            return

        def get_next_bar(self, symbol):
            """Get next bar (not implemented)."""
            return

        def _get_price_tick(self, instrument):
            """Return the minimum price tick for *instrument*.

            Queries CTP via ReqQryInstrument on the first call for each
            instrument and caches the result.  Falls back to a conservative
            estimate derived from the last tick price when the query fails.
            """
            cached = self._price_tick_cache.get(instrument)
            if cached is not None:
                return cached

            spec = self.get_symbol_info(instrument)
            tick = _coerce_float(spec.get("price_tick") or spec.get("tick_size"), 0.0)
            if tick > 0:
                self._price_tick_cache[instrument] = tick
                return tick

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

            order_ref = str(
                payload.get("order_ref") or payload.get("bt_order_ref") or self._next_order_ref()
            )
            volume = _positive_int_lot(
                payload["size"] if "size" in payload else payload.get("volume"),
                "volume",
            )

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
                field.OrderPriceType = "2"  # LimitPrice
                field.TimeCondition = "3"  # GFD (good for day)
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
            field.FrontID = int(
                pending.get("front_id") or getattr(self.trader_client, "_front_id", 0) or 0
            )
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

        def fetch_open_orders(self):
            """Query CTP for currently open orders."""
            if not self.feed or not hasattr(self.feed, "get_open_orders"):
                return []
            response = self.feed.get_open_orders()
            if not response.get_status():
                return []
            orders = []
            for row in response.get_data() or []:
                data = self._order_row_to_dict(row)
                if str(data.get("status") or "").strip().lower() in {
                    "canceled",
                    "cancelled",
                    "completed",
                    "rejected",
                    "expired",
                    "mmp_canceled",
                    "expired_in_match",
                }:
                    continue
                if _coerce_int(data.get("remaining"), 0) <= 0:
                    continue
                orders.append(data)
            return orders

        @staticmethod
        def _order_row_to_dict(row):
            """Convert a CTP order row/container into the store's open-order shape."""
            if hasattr(row, "init_data"):
                row = row.init_data()
            if hasattr(row, "get_order_id"):
                instrument = row.get_order_symbol_name() or row.get_symbol_name() or ""
                order_ref = row.get_client_order_id()
                order_id = row.get_order_id() or order_ref
                size = _coerce_int(row.get_order_size(), 0)
                filled = _coerce_int(row.get_executed_qty(), 0)
                remaining = max(size - filled, _coerce_int(getattr(row, "volume_total", 0), 0))
                status = str(getattr(row.get_order_status(), "value", row.get_order_status()))
                raw_order_info = getattr(row, "order_info", None)
                raw_ctp_status = (
                    raw_order_info.get("OrderStatus") if isinstance(raw_order_info, dict) else None
                )
                raw_submit_status = (
                    raw_order_info.get("OrderSubmitStatus")
                    if isinstance(raw_order_info, dict)
                    else None
                )
                normalized_status = {
                    "new": "accepted",
                    "partially_filled": "partial",
                    "filled": "completed",
                }.get(status, status)
                if raw_ctp_status not in (None, "") or raw_submit_status not in (None, ""):
                    normalized_status = _normalize_ctp_order_status(
                        raw_ctp_status,
                        raw_submit_status,
                        normalized_status,
                    )
                return {
                    "id": order_id,
                    "order_id": order_id,
                    "external_order_id": order_id,
                    "order_ref": order_ref,
                    "symbol": instrument,
                    "data_name": instrument,
                    "instrument": instrument,
                    "exchange_id": row.get_order_exchange_id(),
                    "front_id": getattr(row, "front_id", None),
                    "session_id": getattr(row, "session_id", None),
                    "side": row.get_order_side(),
                    "offset": row.get_order_offset(),
                    "price": row.get_order_price(),
                    "size": size,
                    "filled": filled,
                    "remaining": remaining,
                    "status": normalized_status,
                }

            details = _ctp_extract_fields(row, _CTP_ORDER_FIELDS)
            instrument = _coerce_text(
                details.get("InstrumentID") or details.get("ExchangeInstID") or ""
            )
            order_ref = str(details.get("OrderRef") or "").strip()
            order_sys_id = str(details.get("OrderSysID") or "").strip()
            size = _coerce_int(details.get("VolumeTotalOriginal"), 0)
            filled = _coerce_int(details.get("VolumeTraded"), 0)
            remaining = _coerce_int(details.get("VolumeTotal"), max(size - filled, 0))
            return {
                "id": order_sys_id or order_ref,
                "order_id": order_sys_id or order_ref,
                "external_order_id": order_sys_id or order_ref,
                "order_ref": order_ref,
                "symbol": instrument,
                "data_name": instrument,
                "instrument": instrument,
                "exchange_id": str(details.get("ExchangeID") or "").strip(),
                "front_id": _coerce_int(details.get("FrontID"), 0),
                "session_id": _coerce_int(details.get("SessionID"), 0),
                "side": _ctp_direction(details.get("Direction"), "buy"),
                "offset": _ctp_offset(details.get("CombOffsetFlag"), "open"),
                "price": _coerce_float(details.get("LimitPrice"), 0.0),
                "size": size,
                "filled": filled,
                "remaining": remaining,
                "status": _normalize_ctp_order_status(
                    details.get("OrderStatus"),
                    details.get("OrderSubmitStatus"),
                    "submitted",
                ),
            }

        def poll_broker_update(self):
            """Poll a normalized broker-side order/trade/error update."""
            error_update = self._poll_trader_error_event()
            if error_update is not None:
                return error_update
            if not self._order_updates:
                return None
            return self._order_updates.popleft()

        def _poll_trader_error_event(self):
            """Poll richer CTP order-insert/action errors from TraderClient."""
            getter = getattr(self.trader_client, "wait_error_event", None)
            if not callable(getter):
                return None
            event = getter(timeout=0)
            if not isinstance(event, dict):
                return None

            error_id = _coerce_int(event.get("error_id") or event.get("error_code"), 0)
            error_msg = str(event.get("error_msg") or "")
            if error_id == 0 and not error_msg:
                return None

            field = event.get("field")
            details = dict(field) if isinstance(field, dict) else {}
            details["ErrorID"] = error_id
            details["ErrorMsg"] = error_msg
            details.setdefault("StatusMsg", error_msg)
            details["CtpErrorEvent"] = str(event.get("event") or "")

            order_ref = str(details.get("OrderRef") or "").strip()
            order_sys_id = str(details.get("OrderSysID") or "").strip()
            instrument = _coerce_text(
                details.get("InstrumentID") or details.get("ExchangeInstID") or ""
            )
            exchange_id = str(details.get("ExchangeID") or "").strip()
            pending = self._pending_orders.get(order_ref) if order_ref else {}

            update = {
                "kind": "error",
                "source": "trader",
                "error_code": error_id,
                "error_msg": error_msg,
                "status_msg": error_msg,
                "order_ref": order_ref or None,
                "data_name": (pending or {}).get("data_name") or instrument,
                "instrument": instrument,
                "exchange_id": exchange_id,
                "details": details,
            }
            if order_sys_id:
                update["external_order_id"] = order_sys_id
            return update

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
            tick_volume = (
                max(total_volume - previous_total, 0.0) if previous_total is not None else 0.0
            )
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
                event.datetime = _normalize_datetime(tick_dt)
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
                "exchange_id": str(
                    details.get("ExchangeID") or pending.get("exchange_id") or ""
                ).strip(),
                "front_id": _coerce_int(
                    details.get("FrontID"), _coerce_int(pending.get("front_id"), 0)
                ),
                "session_id": _coerce_int(
                    details.get("SessionID"),
                    _coerce_int(pending.get("session_id"), 0),
                ),
                "status": _normalize_ctp_order_status(
                    details.get("OrderStatus"),
                    details.get("OrderSubmitStatus"),
                    "submitted",
                ),
                "submit_status": str(details.get("OrderSubmitStatus") or ""),
                "status_msg": str(details.get("StatusMsg") or ""),
                "side": _ctp_direction(details.get("Direction"), "buy"),
                "offset": _ctp_offset(
                    details.get("CombOffsetFlag"),
                    pending.get("offset") or "open",
                ),
                "price": _coerce_float(
                    details.get("LimitPrice"), _coerce_float(pending.get("price"), 0.0)
                ),
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
            pending = self._pending_orders.get(order_ref) or self._pending_orders_by_sys_id.get(
                order_sys_id, {}
            )

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
                "exchange_id": str(
                    details.get("ExchangeID") or pending.get("exchange_id") or ""
                ).strip(),
                "side": _ctp_direction(details.get("Direction"), "buy"),
                "offset": _ctp_offset(
                    details.get("OffsetFlag"),
                    pending.get("offset") or "open",
                ),
                "price": _coerce_float(
                    details.get("Price"), _coerce_float(pending.get("price"), 0.0)
                ),
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
        """Gateway-based wrapper for CTP trading via bt_api_py.

        This wrapper provides a unified interface to the bt_api_py GatewayClient
        for CTP (China Futures Exchange) trading operations including market
        data subscription, order management, and account queries.

        Args:
            **kwargs: Gateway configuration parameters including exchange_type,
                asset_type, and other gateway-specific settings.
        """

        def __init__(self, **kwargs):
            """Initialize the CTP gateway client wrapper.

            Args:
                **kwargs: Gateway configuration parameters passed to GatewayClient.
            """
            self._kwargs = dict(kwargs)
            self._kwargs.setdefault("exchange_type", "CTP")
            self._kwargs.setdefault("asset_type", self._kwargs.get("asset_type", "FUTURE"))
            self._client = GatewayClient(**self._kwargs)

        def connect(self):
            """Connect to the CTP gateway."""
            self._client.connect()

        def start(self):
            """Start the gateway client (alias for connect)."""
            self.connect()

        def disconnect(self):
            """Disconnect from the CTP gateway."""
            self._client.disconnect()

        def stop(self):
            """Stop the gateway client (alias for disconnect)."""
            self.disconnect()

        def get_session_state(self):
            """Return gateway session state when the gateway exposes it."""
            getter = getattr(self._client, "get_session_state", None)
            if callable(getter):
                state = getter()
                return dict(state or {}) if isinstance(state, dict) else {}
            state = getattr(self._client, "session_state", None)
            return dict(state or {}) if isinstance(state, dict) else {}

        def subscribe(self, symbols):
            """Subscribe to market data for the given symbols.

            Args:
                symbols: Symbol or list of symbols to subscribe to.

            Returns:
                Subscription result from the gateway client.
            """
            return self._client.subscribe(symbols)

        def poll_tick(self, symbol):
            """Poll and return the next available tick for the symbol.

            Args:
                symbol: The trading symbol to poll tick for.

            Returns:
                Tick data or None if no tick is available.
            """
            return self._client.poll_tick(symbol)

        def get_next_tick(self, symbol):
            """Get the next tick for the symbol.

            Args:
                symbol: The trading symbol.

            Returns:
                Next tick data from the gateway client.
            """
            return self._client.get_next_tick(symbol)

        def has_pending_tick(self, symbol):
            """Check if there is a pending tick for the symbol.

            Args:
                symbol: The trading symbol.

            Returns:
                True if a tick is available, False otherwise.
            """
            return self._client.has_pending_tick(symbol)

        def supports_live_ticks(self, symbol):
            """Check if live ticks are supported for the symbol.

            Args:
                symbol: The trading symbol.

            Returns:
                True if live ticks are supported, False otherwise.
            """
            return self._client.supports_live_ticks(symbol)

        def supports_live_streaming(self, _symbol=None):
            """Check if live streaming is supported.

            Args:
                _symbol: Unused parameter.

            Returns:
                True (live streaming is always supported).
            """
            return True

        def get_balance(self):
            """Get the account balance.

            Returns:
                Account balance data from the gateway client.
            """
            return self._client.get_balance()

        def get_account(self):
            """Get the account information.

            Returns:
                Account data from the gateway client.
            """
            return self._client.get_account()

        def get_positions(self):
            """Get all open positions.

            Returns:
                List of position data from the gateway client.
            """
            return self._client.get_positions()

        def fetch_bars(
            self, symbol, timeframe=None, compression=None, since=None, limit=None, **kwargs
        ):
            """Fetch historical bar data for the symbol.

            Args:
                symbol: Trading symbol to fetch bars for.
                timeframe: Timeframe for the bars (e.g., '1m', '1h', '1d').
                compression: Compression type for the timeframe.
                since: Start time for the bars (ISO format string).
                limit: Maximum number of bars to return (default: 200).
                **kwargs: Additional keyword arguments.

            Returns:
                List of bar data from the gateway client.
            """
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
            """Fetch OHLCV (candlestick) data for the symbol.

            Args:
                symbol: Trading symbol to fetch OHLCV for.
                timeframe: Timeframe for the candles.
                compression: Compression type for the timeframe.
                since: Start time for the candles (ISO format string).
                limit: Maximum number of candles to return.
                **kwargs: Additional keyword arguments.

            Returns:
                List of OHLCV data from fetch_bars.
            """
            return self.fetch_bars(
                symbol,
                timeframe=timeframe,
                compression=compression,
                since=since,
                limit=limit,
                **kwargs,
            )

        def fetch_symbol_info(self, symbol):
            """Fetch information about a trading symbol.

            Args:
                symbol: Trading symbol to get info for.

            Returns:
                Symbol information dict, or empty dict if unavailable.
            """
            return self.get_symbol_info(symbol)

        def get_symbol_info(self, symbol):
            """Get trading symbol metadata from either gateway API alias."""
            for method_name in ("get_symbol_info", "fetch_symbol_info"):
                getter = getattr(self._client, method_name, None)
                if callable(getter):
                    return getter(symbol) or {}
            return {}

        def fetch_open_orders(self):
            """Fetch all open (unfilled) orders.

            Returns:
                List of open order data, or empty list if unavailable.
            """
            if hasattr(self._client, "fetch_open_orders"):
                return self._client.fetch_open_orders()
            return []

        def poll_bar(self, symbol):
            """Poll and return the next available bar for the symbol.

            Args:
                symbol: Trading symbol to poll bar for.

            Returns:
                None (bars not supported in this wrapper).
            """

        def get_next_bar(self, symbol):
            """Get the next bar for the symbol.

            Args:
                symbol: Trading symbol.

            Returns:
                None (bars not supported in this wrapper).
            """

        def submit_order(self, payload):
            """Submit an order to the gateway.

            Args:
                payload: Order payload dict containing order parameters.

            Returns:
                Response from the gateway client.
            """
            response = self._client.submit_order(payload)
            if "data_name" in payload and "data_name" not in response:
                response["data_name"] = payload["data_name"]
            return response

        def create_order(self, **kwargs):
            """Create and submit an order.

            Args:
                **kwargs: Order parameters.

            Returns:
                Response from submit_order.
            """
            return self.submit_order(kwargs)

        def cancel_order(self, order_ref, dataname=None):
            """Cancel an order by its reference.

            Args:
                order_ref: Order reference ID to cancel.
                dataname: Optional data name for the order.

            Returns:
                Response from the gateway client.
            """
            return self._client.cancel_order(order_ref, dataname=dataname)

        def poll_broker_update(self):
            """Poll for broker updates.

            Returns:
                Broker update data from the gateway client.
            """
            return self._client.poll_broker_update()

        @staticmethod
        def _resolve_timeframe(timeframe=None, compression=None):
            """Map backtrader timeframe+compression to gateway timeframe string."""
            if isinstance(timeframe, str) and timeframe.upper() in (
                "M1",
                "M5",
                "M15",
                "M30",
                "H1",
                "H4",
                "D1",
                "W1",
                "MN1",
            ):
                return timeframe.upper()
            comp = int(compression or 1)
            try:
                import backtrader as bt

                tf_val = timeframe
                if tf_val == bt.TimeFrame.Minutes:
                    return {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4"}.get(
                        comp, "M1"
                    )
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


def _resolve_backend(provider: Any, backend: Any = None) -> str:
    text = str(backend or "").strip().lower()
    if text:
        if text not in _BACKENDS:
            raise ValueError(f"Unsupported BtApiStore backend {backend!r}")
        return text
    provider_text = str(provider or "").strip().lower()
    if provider_text == "forwarding":
        return "forwarding"
    if _is_gateway_provider(provider_text):
        return "gateway"
    return "direct"


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
        backend: Optional[str] = None,
        autostart: bool = False,
        **kwargs: Any,
    ):
        """Initialize the BtApiStore.

        Args:
            provider: The provider name (e.g., 'btapi', 'ctp', 'ctp_gateway').
            api: Optional pre-configured API instance.
            api_cls: Optional API class to instantiate.
            config: Optional configuration dictionary.
            api_kwargs: Optional API keyword arguments.
            cash: Initial cash amount (default: 0.0).
            value: Initial portfolio value (default: same as cash).
            account_cache_ttl: Time-to-live for account cache in seconds.
            positions_cache_ttl: Time-to-live for positions cache in seconds.
            open_orders_cache_ttl: Time-to-live for open orders cache in seconds.
            positions: Initial positions list.
            historical_bars: Pre-seeded historical bars by symbol.
            live_bars: Pre-seeded live bars by symbol.
            contract_metadata: Contract metadata by symbol.
            backend: Runtime backend: direct, gateway or forwarding.
            autostart: Whether to start the store on initialization.
            **kwargs: Additional provider-specific arguments.
        """
        self.provider = self._resolve_provider(provider)
        self.backend = _resolve_backend(self.provider, backend)
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
        self._open_orders_cache: list = []
        seeded_at = time.monotonic() if positions or value is not None or cash else 0.0
        self._last_balance_refresh = seeded_at
        self._last_positions_refresh = seeded_at if positions else 0.0
        self._last_open_orders_refresh = 0.0
        self._connected = False
        self._started = False
        self._data_feeds: list = []
        self._broker = None
        self.notifs: Deque[Any] = collections.deque()
        self._historical_bars: dict = collections.defaultdict(collections.deque)
        self._historical_query_cache: Dict[Any, List[Dict[str, Any]]] = {}
        self._live_bars: dict = collections.defaultdict(collections.deque)
        self._subscribed_datanames: set = set()
        self._successful_connect_count = 0
        self.contract_metadata = {
            str(key): dict(value or {}) for key, value in (contract_metadata or {}).items()
        }
        self.session_id = (
            f"{self.provider}-"
            f"{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}-"
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
        if self.backend != "gateway" and not _is_gateway_provider(self.provider):
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
        if "strategy_id" not in self._api_kwargs and "gateway_strategy_id" not in self._api_kwargs:
            strategy_id = os.environ.get("BT_GATEWAY_STRATEGY_ID") or os.environ.get(
                "BT_TRADING_INSTANCE_ID"
            )
            if strategy_id:
                self._api_kwargs["strategy_id"] = strategy_id
        raw = os.environ.get("BT_GATEWAY_START_LOCAL_RUNTIME")
        if raw is not None:
            self._api_kwargs["gateway_start_local_runtime"] = raw not in {"0", "false", "False"}

    @property
    def is_connected(self) -> bool:
        """Return whether the store is connected and ready."""
        return self._connected

    # Credential keys that must never appear in repr/str/logs in cleartext.
    _SENSITIVE_KEYS = frozenset(
        {"password", "passwd", "auth_code", "secret", "token", "api_secret", "private_key"}
    )

    def __repr__(self) -> str:
        """Return a repr with credential fields masked.

        The store keeps live-trading credentials (e.g. CTP ``password`` and
        ``auth_code``) inside ``_api_kwargs``/``_config``. A naive repr would
        leak them into logs, tracebacks and debugger output, so this method
        masks any sensitive key before rendering.
        """
        return (
            f"{type(self).__name__}(provider={self.provider!r}, "
            f"backend={self.backend!r}, "
            f"connected={self._connected}, started={self._started}, "
            f"account={self._masked_account_id()!r})"
        )

    __str__ = __repr__

    @classmethod
    def _mask_sensitive(cls, mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a copy of ``mapping`` with sensitive credential values masked.

        Use this whenever store kwargs/config need to be logged or surfaced for
        debugging so that secrets such as ``password`` and ``auth_code`` are
        never written out in cleartext.
        """
        safe: Dict[str, Any] = {}
        for key, value in (mapping or {}).items():
            if str(key).lower() in cls._SENSITIVE_KEYS:
                safe[key] = "***"
            else:
                safe[key] = value
        return safe

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

    def get_balance(self, force: bool = False, raise_errors: bool = False):
        """Refresh cached cash and value from the API, if available."""
        if not force and self._is_cache_fresh(
            self._last_balance_refresh,
            self._account_cache_ttl,
        ):
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
            if not raise_errors and self._last_balance_refresh > 0.0:
                return {"cash": self._cash, "value": self._value}
            raise

        normalized_balance = _normalise_account_balance_payload(balance)
        if normalized_balance is not None:
            cash, value = normalized_balance
            if cash is not None:
                self._cash = cash
            if value is not None:
                self._value = value
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

    def get_positions(
        self,
        force: bool = False,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return cached or queried positions."""
        if not force and self._is_cache_fresh(
            self._last_positions_refresh,
            self._positions_cache_ttl,
        ):
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
            if not raise_errors and self._last_positions_refresh > 0.0:
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
        if (
            self._is_default_history_request(timeframe, compression, since, limit)
            and self._historical_bars[dataname]
        ):
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

    def fetch_open_orders(
        self,
        force: bool = False,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch the provider's currently open orders, if supported."""
        if not force and self._is_cache_fresh(
            self._last_open_orders_refresh,
            self._open_orders_cache_ttl,
        ):
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
            if not raise_errors and self._last_open_orders_refresh > 0.0:
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
            return cast(Optional[Dict[str, Any]], self._live_bars[dataname].popleft())

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
                raise BtApiStoreError(
                    "Underlying bt_api_py client does not support order submission"
                )
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
        if self._submit_response_looks_accepted(response):
            self.emit_runtime_event(
                "order_submit_accepted",
                order_ref=external_order_id or order_ref,
                details=dict(payload),
                status="accepted",
            )
        else:
            self.emit_runtime_event(
                "order_submit_unconfirmed",
                level="WARNING",
                order_ref=order_ref,
                details=dict(payload),
                status="unconfirmed",
                error_code="invalid_submit_response",
                error_msg="remote submit response did not confirm order acceptance",
            )
        return response

    def cancel_order(self, order):
        """Cancel a submitted order through the unified API."""
        order_ref = (
            getattr(order.info, "external_order_id", None)
            or getattr(order.info, "ctp_order_ref", None)
            or getattr(order, "ref", None)
        )
        dataname = self._extract_dataname(order.data)
        return self.cancel_order_ref(order_ref, dataname=dataname)

    def cancel_order_ref(self, order_ref, dataname: Optional[str] = None):
        """Cancel a provider order by reference without requiring a local Order."""
        api = self._ensure_api_ready()
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

        cancel_error = self._cancel_response_error(response)
        if cancel_error is not None:
            error_code, error_msg = cancel_error
            self.emit_runtime_event(
                "order_cancel_reject_remote",
                level="ERROR",
                order_ref=order_ref,
                details=details,
                error_code=error_code,
                error_msg=error_msg,
                status="rejected",
            )
            raise BtApiStoreError(error_msg)

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
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds"),
            "event_type": str(event_type),
            "level": str(level).upper(),
            "status": status,
            "provider": self.provider,
            "backend": self.backend,
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

    def _is_ctp_session_provider(self) -> bool:
        if self.backend == "forwarding":
            return False
        provider = str(self.provider or "").strip().lower()
        if provider in {"ctp", "ctp_gateway"}:
            return True
        if self.backend != "gateway":
            return False
        exchange = (
            self._api_kwargs.get("exchange_type")
            or self._api_kwargs.get("exchange")
            or self._config.get("exchange_type")
            or self._config.get("exchange")
            or "CTP"
        )
        return str(exchange or "").strip().upper() == "CTP"

    def _ctp_auth_request_details(self) -> Dict[str, Any]:
        broker_id = self._api_kwargs.get("broker_id") or self._config.get("broker_id") or ""
        app_id = self._api_kwargs.get("app_id") or self._config.get("app_id") or ""
        auth_code = self._api_kwargs.get("auth_code") or self._config.get("auth_code") or ""
        details = {
            "broker_id": str(broker_id or ""),
            "app_id": str(app_id or ""),
            "has_auth_code": bool(auth_code),
        }
        return {key: value for key, value in details.items() if value not in {"", None}}

    def _read_ctp_session_state(self) -> Dict[str, Any]:
        targets = [self._api]
        for attr in ("trader_client", "_client"):
            target = getattr(self._api, attr, None)
            if target is not None:
                targets.append(target)

        states: List[Dict[str, Any]] = []
        for target in targets:
            getter = getattr(target, "get_session_state", None)
            if not callable(getter):
                continue
            try:
                state = getter()
            except Exception as exc:
                logger.debug("Failed to read CTP session state: %s", exc)
                continue
            if isinstance(state, dict):
                states.append(dict(state))

        state = getattr(self._api, "session_state", None)
        if isinstance(state, dict):
            states.append(dict(state))

        if not states:
            return {}

        def _state_score(item: Dict[str, Any]) -> int:
            auth_state = str(item.get("auth_state") or "").strip().lower()
            login_state = str(item.get("login_state") or "").strip().lower()
            score = 0
            if auth_state == "failed" or login_state in {"blocked", "failed"}:
                return 100
            if item.get("ready") is True:
                score += 20
            if auth_state in {"authenticated", "success", "ready", "logged_in"}:
                score += 10
            elif auth_state and auth_state not in {"unknown", "idle"}:
                score += 1
            if login_state in {"logged_in", "ready"}:
                score += 10
            elif login_state and login_state not in {"unknown", "idle"}:
                score += 1
            for key in ("front_id", "session_id", "trading_day", "login_time", "system_name"):
                if item.get(key) not in {None, ""}:
                    score += 1
            return score

        return max(states, key=_state_score)

    @staticmethod
    def _ctp_error_from_state(state: Dict[str, Any], key: str, default_msg: str) -> Tuple[str, str]:
        error = state.get(key) or {}
        if not isinstance(error, dict):
            error = {}
        code = error.get("error_id", error.get("error_code", ""))
        msg = error.get("error_msg", error.get("message", "")) or default_msg
        return str(code or ""), str(msg or "")

    @staticmethod
    def _ctp_session_details(state: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("front_id", "session_id", "trading_day", "login_time", "system_name", "broker_id")
        return {key: state.get(key) for key in keys if state.get(key) not in {None, ""}}

    def _emit_ctp_session_events(self, *, emit_success: bool = True) -> None:
        state = self._read_ctp_session_state()
        auth_state = str(state.get("auth_state") or "").strip().lower()
        login_state = str(state.get("login_state") or "").strip().lower()

        if auth_state == "failed":
            code, msg = self._ctp_error_from_state(
                state, "last_auth_error", "authentication failed"
            )
            self.emit_runtime_event(
                "store_auth_failed",
                level="ERROR",
                status="failed",
                error_code=code,
                error_msg=msg,
                details=self._ctp_session_details(state),
            )
            raise BtApiStoreError(f"CTP authentication failed: {msg}")

        if login_state in {"blocked", "failed"}:
            code, msg = self._ctp_error_from_state(state, "last_login_error", "login failed")
            self.emit_runtime_event(
                "store_login_failed",
                level="ERROR",
                status="failed",
                error_code=code,
                error_msg=msg,
                details=self._ctp_session_details(state),
            )
            raise BtApiStoreError(f"CTP trader login failed: {msg}")

        if not emit_success:
            return

        details = self._ctp_session_details(state)
        if auth_state in {"authenticated", "success", "ready", "logged_in"}:
            self.emit_runtime_event("store_auth_success", status="ready", details=details)
        if login_state in {"logged_in", "ready"} or state.get("ready") is True:
            self.emit_runtime_event("store_login_success", status="ready", details=details)

    def get_notifications(self):
        """Return and clear pending notifications."""
        items = list(self.notifs)
        self.notifs.clear()
        return items

    def get_contract_metadata(self, dataname: Optional[str] = None):
        """Return configured contract metadata for a single symbol or all symbols."""
        if dataname is None:
            return {key: dict(value) for key, value in self.contract_metadata.items()}

        aliases = _contract_metadata_aliases(dataname)
        for alias in aliases:
            metadata = self.contract_metadata.get(alias, {})
            if metadata:
                self.contract_metadata.setdefault(str(dataname), dict(metadata))
                return dict(metadata)
        alias_set = set(aliases)
        for key, value in self.contract_metadata.items():
            if value and alias_set.intersection(_contract_metadata_aliases(key)):
                self.contract_metadata.setdefault(str(dataname), dict(value))
                return dict(value)

        try:
            api = self._ensure_api_ready()
        except Exception:
            return {}

        metadata = _query_contract_metadata_from_api(api, aliases or [str(dataname)], dataname)
        if not metadata:
            return {}

        normalized = dict(metadata)
        if normalized:
            keys = set(aliases)
            for value in (
                normalized.get("symbol"),
                normalized.get("instrument"),
                normalized.get("instId"),
                normalized.get("instrument_id"),
            ):
                keys.update(_contract_metadata_aliases(value))
            for key in keys:
                if key:
                    self.contract_metadata[key] = dict(normalized)
        return normalized

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
        for key in [
            cache_key for cache_key in self._historical_query_cache if cache_key[0] == key_prefix
        ]:
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
            if self.backend == "forwarding":
                self._api = self._create_forwarding_client()
            else:
                if self.backend == "gateway":
                    api_cls = self._api_cls or _create_ctp_gateway_wrapper_class()
                else:
                    api_cls = self._api_cls or _resolve_bt_api_client(self.provider)
                kwargs = dict(self._config)
                kwargs.update(self._api_kwargs)
                self._api = api_cls(**kwargs)

        ctp_session_provider = self._is_ctp_session_provider()
        self.emit_runtime_event("store_connecting", status="connecting")
        if ctp_session_provider:
            self.emit_runtime_event(
                "store_auth_request",
                status="pending",
                details=self._ctp_auth_request_details(),
            )

        try:
            if hasattr(self._api, "connect"):
                self._api.connect()
            elif hasattr(self._api, "start"):
                self._api.start()
        except Exception as exc:
            if ctp_session_provider:
                self._emit_ctp_session_events(emit_success=False)
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
        if ctp_session_provider:
            try:
                self._emit_ctp_session_events()
            except BtApiStoreError:
                self._connected = False
                raise
        self.emit_runtime_event("store_ready", status="ready")
        self.get_balance()
        return self._api

    def _create_forwarding_client(self):
        """Create an embedded or ZMQ forwarding client from store kwargs."""
        try:
            from bt_api_py.forwarding import ForwardingClient, ZmqForwardingClient
        except ImportError as exc:
            raise BtApiMissingDependencyError(
                "bt_api_py.forwarding is required for BtApiStore backend='forwarding'"
            ) from exc

        kwargs = dict(self._config)
        kwargs.update(self._api_kwargs)
        market_endpoint = kwargs.get("market_endpoint") or kwargs.get("gateway_market_endpoint")
        command_endpoint = kwargs.get("command_endpoint") or kwargs.get("gateway_command_endpoint")
        private_endpoint = kwargs.get("private_endpoint") or kwargs.get("gateway_event_endpoint")
        exchange = kwargs.get("exchange") or kwargs.get("exchange_type") or "SIM"
        market_type = kwargs.get("market_type") or kwargs.get("asset_type") or "SPOT"
        account_id = kwargs.get("account_id") or "paper"
        strategy_id = kwargs.get("strategy_id") or "default"
        event_cache_size = kwargs.get("event_cache_size", 4096)
        if market_endpoint or command_endpoint:
            if not market_endpoint or not command_endpoint:
                raise ValueError(
                    "BtApiStore backend='forwarding' requires both market_endpoint "
                    "and command_endpoint for ZeroMQ forwarding"
                )
            return ZmqForwardingClient(
                market_endpoint=str(market_endpoint),
                command_endpoint=str(command_endpoint),
                private_endpoint=str(private_endpoint) if private_endpoint else None,
                exchange=str(exchange),
                market_type=str(market_type),
                account_id=str(account_id),
                strategy_id=str(strategy_id),
                command_timeout_ms=int(kwargs.get("command_timeout_ms", 2000) or 2000),
                event_cache_size=event_cache_size,
            )
        return ForwardingClient(
            bus=kwargs.get("bus"),
            exchange=str(exchange),
            market_type=str(market_type),
            account_id=str(account_id),
            strategy_id=str(strategy_id),
            replay=int(kwargs.get("replay", 0) or 0),
            command_timeout=float(kwargs.get("command_timeout", 2.0) or 2.0),
            event_cache_size=event_cache_size,
        )

    def _order_to_payload(self, order) -> Dict[str, Any]:
        """Convert a backtrader order into a generic bt_api_py payload."""
        from ..order import OrderBase

        order_type_str = self._order_type_to_payload(order)
        if getattr(order, "exectype", None) == OrderBase.Market or order_type_str == "market":
            price = None
        elif order_type_str == "stop_limit":
            price = order.pricelimit if order.pricelimit is not None else order.created.price
            if price is not None and float(price) <= 0:
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
            payload["limit_price"] = order.pricelimit
        if order_type_str in {"stop", "stop_limit"} and order.price is not None:
            payload["stop_price"] = order.price
            extra_data = dict(payload.get("extra_data") or {})
            extra_data.setdefault("aux_price", order.price)
            payload["extra_data"] = extra_data

        offset = getattr(getattr(order, "info", {}), "get", lambda *_args, **_kwargs: None)(
            "offset"
        )
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
    def _order_type_to_payload(order) -> str:
        """Return the canonical bt_api_py order type for a backtrader order."""
        from ..order import OrderBase

        exectype = getattr(order, "exectype", None)
        mapping = {
            OrderBase.Market: "market",
            OrderBase.Close: "market",
            OrderBase.Limit: "limit",
            OrderBase.Stop: "stop",
            OrderBase.StopLimit: "stop_limit",
        }
        if exectype in mapping:
            return mapping[exectype]

        name = str(order.getordername() or "").strip().lower()
        name = name.replace("-", "_").replace(" ", "_")
        aliases = {
            "stoplimit": "stop_limit",
            "stoptraillimit": "stop_trail_limit",
            "stoptrail": "stop_trail",
        }
        return aliases.get(name, name)

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
        current = BtApiStore._unwrap_submit_response(response)
        if isinstance(current, dict):
            return (
                current.get("id")
                or current.get("order_id")
                or current.get("orderId")
                or current.get("ordId")
                or current.get("OrderID")
                or current.get("external_order_id")
                or current.get("externalOrderId")
                or current.get("venue_order_id")
                or current.get("venueOrderId")
                or current.get("ticket")
            )
        return None

    @classmethod
    def _submit_response_looks_accepted(cls, response: Any) -> bool:
        """Return whether a submit response is strong enough for an accepted event."""
        current = cls._unwrap_submit_response(response)
        if current is None or isinstance(current, bool):
            return False
        if isinstance(current, str):
            return bool(current.strip())
        if isinstance(current, (int, float)):
            return current != 0
        if not isinstance(current, dict) or not current:
            return False

        status = str(current.get("status") or current.get("order_status") or "").strip().lower()
        if status in {
            "error",
            "failed",
            "fail",
            "rejected",
            "reject",
            "cancelled",
            "canceled",
            "expired",
        }:
            return False
        if status in {
            "ok",
            "success",
            "submitted",
            "accepted",
            "completed",
            "complete",
            "partial",
            "filled",
            "open",
            "placed",
        }:
            return True

        retcode = current.get("retcode") or current.get("ret_code")
        if retcode not in (None, ""):
            try:
                return int(retcode) in {10008, 10009, 10010}
            except (TypeError, ValueError):
                return False

        code = current.get("code")
        if code not in (None, "", 0, "0"):
            return False

        success_value = current.get("success")
        if isinstance(success_value, bool):
            return success_value

        return cls._submit_response_has_identity(current)

    @staticmethod
    def _unwrap_submit_response(response: Any) -> Any:
        current = response
        for _ in range(5):
            if isinstance(current, (list, tuple)):
                if len(current) == 1 and isinstance(current[0], dict):
                    current = current[0]
                    continue
                return current
            if not isinstance(current, dict):
                return current
            status = str(current.get("status") or "").strip().lower()
            code = str(current.get("code") or "").strip()
            success = current.get("success")
            wrapper_ok = (
                status in {"ok", "success"}
                or code in {"0", "00000"}
                or success is True
            )
            if wrapper_ok:
                nested = current.get("data", current.get("result"))
                if isinstance(nested, dict):
                    current = nested
                    continue
                if (
                    isinstance(nested, (list, tuple))
                    and len(nested) == 1
                    and isinstance(nested[0], dict)
                ):
                    current = nested[0]
                    continue
            return current
        return current

    @staticmethod
    def _submit_response_has_identity(response: dict[str, Any]) -> bool:
        for key in (
            "id",
            "order_id",
            "orderId",
            "OrderID",
            "ordId",
            "external_order_id",
            "externalOrderId",
            "venue_order_id",
            "venueOrderId",
            "order_ref",
            "orderRef",
            "OrderRef",
            "client_order_id",
            "clientOrderId",
            "newClientOrderId",
            "origClientOrderId",
            "clOrdId",
            "origClOrdId",
            "ticket",
            "order",
            "deal",
            "deal_id",
            "dealId",
            "DealID",
        ):
            if response.get(key) not in (None, ""):
                return True
        return False

    @classmethod
    def _cancel_response_error(cls, response: Any) -> tuple[str, str] | None:
        current = cls._unwrap_submit_response(response)
        if current is None:
            return "empty_cancel_response", "empty remote cancel response"
        if isinstance(current, bool):
            if current:
                return None
            return "invalid_cancel_response", "invalid remote cancel response"
        if isinstance(current, str):
            if current.strip():
                return None
            return "empty_cancel_response", "empty remote cancel response"
        if isinstance(current, (int, float)):
            if current != 0:
                return None
            return "invalid_cancel_response", "invalid remote cancel response"
        if not isinstance(current, dict):
            return "invalid_cancel_response", "invalid remote cancel response"
        if not current:
            return "empty_cancel_response", "empty remote cancel response"

        status = str(current.get("status") or current.get("order_status") or "").strip().lower()
        if status in {
            "error",
            "failed",
            "fail",
            "rejected",
            "reject",
            "denied",
        }:
            return "remote_cancel_rejected", cls._cancel_response_message(
                current, f"remote cancel status: {status}"
            )
        if status in {
            "ok",
            "success",
            "submitted",
            "accepted",
            "pending",
            "pending_cancel",
            "cancel_requested",
            "cancel_submitted",
            "cancelled",
            "canceled",
        }:
            return None

        retcode = current.get("retcode") or current.get("ret_code")
        if retcode not in (None, ""):
            try:
                retcode_int = int(retcode)
            except (TypeError, ValueError):
                retcode_int = None
            if retcode_int in {10008, 10009, 10010}:
                return None
            return "remote_cancel_rejected", cls._cancel_response_message(
                current, f"remote cancel retcode: {retcode}"
            )

        code = current.get("code")
        if code not in (None, "", 0, "0"):
            return "remote_cancel_rejected", cls._cancel_response_message(
                current, f"remote cancel code: {code}"
            )

        success_value = current.get("success")
        if isinstance(success_value, bool):
            if success_value:
                return None
            return "remote_cancel_rejected", cls._cancel_response_message(
                current,
                "remote cancel success flag is false",
            )

        if cls._submit_response_has_identity(current):
            return None
        return "invalid_cancel_response", "invalid remote cancel response"

    @staticmethod
    def _cancel_response_message(response: dict[str, Any], fallback: str) -> str:
        return str(
            response.get("retcode_external")
            or response.get("comment")
            or response.get("message")
            or response.get("error")
            or response.get("reason")
            or fallback
        )

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
        for key in (
            "order_id",
            "external_order_id",
            "order_ref",
            "client_order_id",
            "bt_order_ref",
            "filled",
            "remaining",
            "position_side",
            "trade_type",
            "liquidity",
            "commission_role",
            "commission",
            "comm",
            "fee",
            "fees",
            "trade_fee",
            "trade_commission",
            "commission_amount",
            "fee_currency",
            "commission_asset",
            "trade_fee_symbol",
            "status_msg",
            "error_code",
        ):
            value = update.get(key)
            if value not in (None, ""):
                details[key] = value
        for key, value in dict(update.get("details") or {}).items():
            if key not in details or details.get(key) in (None, ""):
                details[key] = value

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

        if kind == "position":
            details.update(
                {
                    "position_id": update.get("position_id"),
                    "volume": update.get("volume"),
                    "profit": update.get("profit"),
                    "commission": update.get("commission"),
                }
            )
            self.emit_runtime_event(
                "position_update",
                status="updated",
                details=details,
            )
            return

        if kind == "error":
            event_type = "order_reject_remote" if update.get("order_ref") else "store_error"
            self.emit_runtime_event(
                event_type,
                level="ERROR",
                status="error",
                order_ref=update.get("order_ref"),
                error_code=str(update.get("error_code") or ""),
                error_msg=str(update.get("error_msg") or ""),
                details=details,
            )
