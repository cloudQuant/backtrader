#!/usr/bin/env python
"""Unified bt_api_py-backed live store.

This module centralizes live trading integrations behind a single store
implementation. Venue-specific adapters such as CTP, CCXT, IB, Oanda,
Futu, and VC are intentionally removed from the public surface.
"""

from __future__ import annotations

import asyncio
import collections
import datetime as _dt
import hashlib
import heapq
import hmac
import importlib
import inspect
import itertools
import json
import math
import os
import re
import sys
import threading
import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple, cast

from ..events import OrderBookSnapshot, TickEvent
from ..utils.log_message import get_logger
from .livestore import LiveStoreBase

logger = get_logger(__name__)

_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()

_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|auth[_-]?code|credential(?:s)?|"
    r"authorization|listen[_-]?key|passphrase|passwd|password|private[_-]?key|"
    r"secret(?:[_-]?key)?|signature|(?:access|session)[_-]?token|token)\b"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)([^,;\s\"'}]+)"
)
_AUTHORIZATION_TEXT_RE = re.compile(r"(?i)\b(bearer|basic)\s+[^,;\s]+")
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|authorization|listen[_-]?key|signature|"
    r"(?:access|session)[_-]?token|token)=)[^&#\s]*"
)


def _redact_diagnostic(value: Any) -> Any:
    """Recursively remove credential material from diagnostic values."""
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, Mapping):
        return {
            key: "***" if BtApiStore._is_sensitive_key(key) else _redact_diagnostic(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_diagnostic(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_diagnostic(item) for item in value)
    if isinstance(value, set):
        # A member may normalize to a mapping, which is intentionally
        # unhashable. Diagnostics do not need to preserve set identity.
        return [_redact_diagnostic(item) for item in value]
    if isinstance(value, frozenset):
        return tuple(_redact_diagnostic(item) for item in value)
    if isinstance(value, str):
        value = _AUTHORIZATION_TEXT_RE.sub(r"\1 ***", value)
        value = _SENSITIVE_TEXT_RE.sub(r"\1\2***", value)
        return _SENSITIVE_QUERY_RE.sub(r"\1***", value)
    if value is None or isinstance(value, (bool, int, float, Decimal)):
        return value
    # Diagnostics must never rely on an arbitrary object's repr: vendor
    # exceptions and transport objects commonly include credentials there.
    try:
        return BtApiStore._masked_copy(value)
    except Exception:
        return type(value).__name__


def _safe_log(level: str, message: str, *args: Any) -> None:
    """Write a diagnostic without allowing a broken sink into trading control flow."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        _LOGGING_HEALTH["logging_errors"] += 1


_COMMAND_PRIORITY = {
    "reconcile": 0,
    "query": 0,
    "cancel": 1,
    "close": 2,
    "open": 3,
}

_SDK_EXECUTION_CONFIG_KEYS = (
    "order_journal",
    "require_order_journal",
    "market_data_only",
    "order_poll_interval",
    "account_currency",
    "account_currencies",
    "account_ids",
    "required_environments",
    "strategy_id",
    "strategy_identity_sha256",
    "account_maximum_loss_bps",
    "account_risk_max_age_seconds",
)

_CTP_EXECUTION_ARM_FIELDS = frozenset(
    {
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "receipt_sha256",
        "native_sha256",
        "ctp_package_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "preflight_sha256",
    }
)
_CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION = "ctp-contract-bundle-v1"


def _is_ctp_approval_capability(value: Any) -> bool:
    """Return whether the opaque object is a redeemed SDK approval capability."""

    if value is None:
        return False
    try:
        from bt_api_py import CtpExecutionApprovalCapability
    except ImportError:  # pragma: no cover - SDK without approval contracts
        return False
    return type(value) is CtpExecutionApprovalCapability


# Query timestamps are produced by the SDK/native boundary while the Store
# records the local send/receive envelope.  The direct CTP path uses one host
# clock, so no guessed wall-clock tolerance can turn an out-of-window response
# into complete evidence.
_CTP_EXECUTION_ARM_BUNDLE_FIELDS = frozenset(
    {*_CTP_EXECUTION_ARM_FIELDS, "scope_version", "authorized_instruments"}
)

_CTP_WRITE_REQUEST_TYPES = (
    "settlement_confirm",
    "order_insert",
    "order_action",
)

_CTP_EXECUTION_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_kind",
        "authorization_key_id",
        "receipt_sha256",
        "signature_hmac_sha256",
        "issued_at_utc",
        "expires_at_utc",
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "stage_a_snapshot_sha256",
        "stage_a_query_request_ids",
        "stage_b_snapshot_sha256",
        "stage_b_query_request_ids",
        "preflight_sha256",
        "runtime_executable_sha256",
        "native_sha256",
        "ctp_package_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "evidence_hashes_sha256",
        "gate_statuses",
    }
)
_CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS = frozenset(
    {*_CTP_EXECUTION_AUTHORIZATION_FIELDS, "scope_version", "authorized_instruments"}
)

_CTP_STAGE_A_QUERY_NAMES = ("account", "positions", "orders", "trades", "instruments")
_CTP_STAGE_B_QUERY_NAMES = _CTP_STAGE_A_QUERY_NAMES + ("margin_rate", "commission_rate")

_CTP_EXECUTION_RECOVERY_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "recovery_required",
        "can_arm_execution",
        "can_arm_recovery",
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "strategy_id",
        "execution_cycle_id",
        "remote_position",
        "owned_position",
        "allowed_closes",
        "allowed_cancels",
        "allowed_actions",
        "unknown_ids",
        "evidence_errors",
        "journal_sha256",
        "fencing_epoch",
        "recovery_token_sha256",
    }
)
_CTP_EXECUTION_RECOVERY_BUNDLE_FIELDS = frozenset(
    {
        *_CTP_EXECUTION_RECOVERY_FIELDS,
        "scope_version",
        "authorized_instruments",
        "remote_positions_by_instrument",
        "owned_positions_by_instrument",
    }
)
_CTP_RECOVERY_POSITION_FIELDS = frozenset(
    {"long_today", "long_yesterday", "short_today", "short_yesterday"}
)
_CTP_RECOVERY_CLOSE_FIELDS = frozenset(
    {
        "execution_cycle_id",
        "symbol",
        "exchange_id",
        "position_side",
        "side",
        "offset",
        "quantity",
        "quantity_unit",
    }
)
_CTP_RECOVERY_CANCEL_FIELDS = frozenset(
    {
        "execution_cycle_id",
        "symbol",
        "exchange_id",
        "client_order_id",
        "order_id",
        "order_ref",
        "front_id",
        "session_id",
    }
)
_CTP_EXECUTION_RECOVERY_ARM_FIELDS = frozenset(
    {
        "armed",
        "market_data_only",
        "recovery_only",
        "proof_sha256",
        "recovery_token_sha256",
        "execution_cycle_id",
    }
)
_CTP_EXECUTION_RECOVERY_COMPLETE_FIELDS = frozenset(
    {
        "completed",
        "armed",
        "market_data_only",
        "recovery_only",
        "requires_new_preflight",
        "recovery_token_sha256",
    }
)

_DEFINITE_READINESS_REASONS = frozenset(
    {
        "account_level_has_no_derivatives",
        "instrument_not_live",
        "invalid_expected_position_mode",
        "invalid_quantity_native",
        "max_buy_insufficient",
        "max_sell_insufficient",
        "position_mode_mismatch",
        "quantity_below_minimum",
        "quantity_below_min_size",
        "quantity_not_multiple_of_lot_size",
        "quantity_not_on_step",
        "trading_permission_denied",
    }
)


def _contract_mapping(value: Any, contract_name: str) -> Dict[str, Any]:
    """Convert a public SDK mapping/dataclass without importing venue schemas."""
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise BtApiStoreError(f"{contract_name} must be a mapping or dataclass")


def _sdk_cross_venue_contracts():
    """Load public SDK validation primitives without a core import dependency.

    Backtrader's generic Store remains importable without the optional SDK.
    When it is configured for ``provider='btapi'``, validation comes from the
    SDK's public cross-venue contract rather than a local venue-schema copy.
    """

    try:
        from bt_api_py.cross_venue import (
            CrossVenueValueError,
            coerce_funding_snapshot,
            normalize_orderbook_evidence,
        )
    except ImportError as exc:
        raise BtApiMissingDependencyError(
            "BtApiStore cross-venue validation requires bt_api_py"
        ) from exc
    return CrossVenueValueError, coerce_funding_snapshot, normalize_orderbook_evidence


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
_CTP_QUERY_RECORD_FIELDS = tuple(
    dict.fromkeys(
        _CTP_ORDER_FIELDS
        + _CTP_TRADE_FIELDS
        + (
            "AccountID",
            "Available",
            "Balance",
            "CloseProfit",
            "Commission",
            "CloseRatioByMoney",
            "CloseRatioByVolume",
            "CloseTodayRatioByMoney",
            "CloseTodayRatioByVolume",
            "CombinationType",
            "CurrMargin",
            "CreateDate",
            "DeliveryMonth",
            "DeliveryYear",
            "EndDelivDate",
            "ExchangeID",
            "ExchangeInstID",
            "ExchFixedMargin",
            "ExchMiniMargin",
            "ExpireDate",
            "FixedMargin",
            "HedgeFlag",
            "InstrumentID",
            "InstLifePhase",
            "IsTrading",
            "InvestUnitID",
            "InvestorID",
            "LongFrozen",
            "LongMarginRatio",
            "LongMarginRatioByMoney",
            "LongMarginRatioByVolume",
            "LowerLimitPrice",
            "MaxMarginSideAlgorithm",
            "MaxLimitOrderVolume",
            "MaxMarketOrderVolume",
            "MinLimitOrderVolume",
            "MinMarketOrderVolume",
            "MiniMargin",
            "OpenDate",
            "OpenInterest",
            "OpenRatioByMoney",
            "OpenRatioByVolume",
            "OptionsType",
            "PosiDirection",
            "Position",
            "PositionCost",
            "PositionProfit",
            "PositionDateType",
            "PositionType",
            "PriceTick",
            "ProductID",
            "ProductClass",
            "Royalty",
            "ShortFrozen",
            "ShortMarginRatio",
            "ShortMarginRatioByMoney",
            "ShortMarginRatioByVolume",
            "StartDelivDate",
            "StrikePrice",
            "StrikeRatioByMoney",
            "StrikeRatioByVolume",
            "TodayPosition",
            "TradingDay",
            "UnderlyingInstrID",
            "UnderlyingMultiple",
            "UpperLimitPrice",
            "Volume",
            "VolumeMultiple",
            "YdPosition",
            "ranking_trading_day",
            "trading_days_to_expiry",
        )
    )
)


class BtApiStoreError(Exception):
    """Base error for btapi store failures."""


class _ApprovalLeaseRejected(BtApiStoreError):
    """Definite local rejection raised before an SDK write crosses its lease."""

    definite_reject = True

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


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
        list_candidates: List[Dict[str, Any]] = []
        for item in raw:
            list_candidates.extend(_account_payload_candidates(item, depth=depth + 1))
        return list_candidates

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
            _safe_log("debug", "Failed to coerce value to text: %s", e)
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
        _safe_log("debug", "Failed to get attr %s from %s: %s", attr, type(obj).__name__, e)
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
            selected_row: Optional[Dict[str, Any]]
            if isinstance(payload, dict):
                selected_row = payload
            else:
                selected_row = _select_contract_payload_row(payload, symbol)
            if selected_row is None:
                continue
            base = {
                item_key: item_value for item_key, item_value in data.items() if item_key != key
            }
            base.update(selected_row)
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
    if key_lower in {"makeru", "takeru"} or (okx_fee_sign and key_lower in {"maker", "taker"}):
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
        str(metadata.get(key) or "") for key in ("source", "fee_source", "exchange", "exchange_id")
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
        attempt_groups: List[List[Tuple[Tuple[Any, ...], Dict[str, Any]]]] = []
        for query_symbol in aliases:
            attempts = _contract_metadata_method_attempts(api, method_name, query_symbol)
            if attempts:
                attempt_groups.append(attempts)
        attempt_groups.extend(
            [attempt]
            for attempt in _contract_metadata_method_attempts(
                api, method_name, "", include_empty_call=True
            )
        )
        for attempts in attempt_groups:
            for args, kwargs in attempts:
                try:
                    payload = method(*args, **kwargs)
                except Exception:
                    continue
                metadata = _normalise_contract_metadata(payload, symbol, source=method_name)
                if _contract_metadata_has_rules(metadata):
                    if fee_metadata:
                        fee_source = fee_metadata.get("source")
                        metadata.update(
                            {key: value for key, value in fee_metadata.items() if key != "source"}
                        )
                        if fee_source:
                            metadata["fee_source"] = fee_source
                    return metadata
                # The method accepted this call shape. An empty result means
                # the symbol alias was not found, not that another call shape
                # should repeat the same remote lookup.
                break
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


def _canonical_ctp_scope(symbol: Any, exchange_id: Any = "") -> str:
    """Return an exchange-qualified CTP instrument or an empty string."""
    instrument, parsed_exchange = _split_ctp_symbol(symbol)
    exchange = _coerce_text(exchange_id or parsed_exchange).upper()
    instrument = _normalize_ctp_instrument(instrument, exchange).upper()
    product_match = re.fullmatch(r"([A-Z]+)(\d{3,4})", instrument)
    if not exchange and product_match and product_match.group(1) in _CZCE_PRODUCT_PREFIXES:
        exchange = "CZCE"
        instrument = _normalize_ctp_instrument(instrument, exchange).upper()
    if exchange not in _CTP_EXCHANGES or re.fullmatch(r"[A-Z]+\d{3,4}", instrument) is None:
        return ""
    return f"{exchange}.{instrument}"


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
            _safe_log("debug", "Failed to read CTP field attr %s: %s", attr, e)
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
            _safe_log("debug", "Failed to read CTP field attr %s: %s", attr, e)
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
            # Settlement confirmation is a terminal write.  The legacy
            # direct CTP wrapper is used for observation and typed query
            # preflights too, so an omitted setting must stay read-only.  A
            # managed SDK execution session performs the explicit confirmed
            # transition instead of reviving this former implicit write.
            auto_confirm = kwargs.get("auto_settlement_confirm", False)
            if isinstance(auto_confirm, str):
                auto_confirm = auto_confirm.strip().lower() in {"1", "true", "yes", "on"}
            self.auto_settlement_confirm = bool(auto_confirm)

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
            if self.auto_settlement_confirm is not False:
                raise BtApiStoreError(
                    "auto_settlement_confirm=True is not permitted by the CTP direct wrapper"
                )
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
            trader_kwargs = {
                "front": self.td_front,
                "broker_id": self.broker_id,
                "user_id": self.user_id,
                "password": self.password,
                "app_id": self.app_id,
                "auth_code": self.auth_code,
            }
            try:
                trader_parameters = inspect.signature(TraderClient).parameters.values()
            except (TypeError, ValueError):
                trader_parameters = ()
            if any(
                item.name == "auto_settlement_confirm" or item.kind == inspect.Parameter.VAR_KEYWORD
                for item in trader_parameters
            ):
                trader_kwargs["auto_settlement_confirm"] = self.auto_settlement_confirm
            self.trader_client = TraderClient(**trader_kwargs)
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
                state = dict(self.trader_client.get_session_state())
                state.setdefault("auto_settlement_confirm", self.auto_settlement_confirm)
                return state
            return {
                "connected": bool(self._connected),
                "ready": False,
                "auth_state": "unknown",
                "login_state": "unknown",
                "auto_settlement_confirm": self.auto_settlement_confirm,
            }

        def _query_result(self, method_name, **kwargs):
            """Delegate a typed query without converting incomplete results to empty data."""
            if not self.trader_client:
                raise BtApiStoreError("CTP trader client is not available")
            method = getattr(self.trader_client, method_name, None)
            if not callable(method):
                raise BtApiStoreError(f"CTP query capability unavailable: {method_name}")
            return method(**kwargs)

        def query_account_result(self, timeout=5):
            return self._query_result("query_account_result", timeout=timeout)

        def query_positions_result(self, timeout=5):
            return self._query_result("query_positions_result", timeout=timeout)

        def query_orders_result(self, timeout=5, **kwargs):
            return self._query_result("query_orders_result", timeout=timeout, **kwargs)

        def query_trades_result(self, timeout=5, **kwargs):
            return self._query_result("query_trades_result", timeout=timeout, **kwargs)

        def query_instruments_result(self, instrument_id="", exchange_id="", timeout=5):
            return self._query_result(
                "query_instruments_result",
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                timeout=timeout,
            )

        def query_instrument_margin_rate_result(
            self, instrument_id, exchange_id="", hedge_flag="1", timeout=5
        ):
            return self._query_result(
                "query_instrument_margin_rate_result",
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                hedge_flag=hedge_flag,
                timeout=timeout,
            )

        def query_instrument_commission_rate_result(self, instrument_id, exchange_id="", timeout=5):
            return self._query_result(
                "query_instrument_commission_rate_result",
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                timeout=timeout,
            )

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
                    _safe_log("debug", "CTP %s failed: %s", method_name, exc)
                    return None
            except Exception as exc:
                _safe_log("debug", "CTP %s failed: %s", method_name, exc)
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
            if order_type != "limit":
                raise BtApiStoreError(f"Unsupported CTP order type: {order_type}")

            time_in_force = str(payload.get("time_in_force") or "GFD").strip().upper()
            if time_in_force in {"GOOD_FOR_DAY", "GOOD-FOR-DAY"}:
                time_in_force = "GFD"
            if time_in_force != "GFD":
                raise BtApiStoreError(
                    f"Unsupported CTP time_in_force: {time_in_force or '<empty>'}; GFD required"
                )

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
            if price <= 0:
                raise BtApiStoreError("CTP limit order requires a positive price")
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
                "time_in_force": "GFD",
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
                _safe_log("debug", "Failed to resolve timeframe: %s", e)
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
        sdk_options = {**self._config, **self._api_kwargs}
        self._ctp_execution_authorization_key_id = str(
            sdk_options.get("execution_authorization_key_id")
            or os.environ.get("BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID")
            or ""
        ).strip()
        self._ctp_execution_authorization_secret = str(
            sdk_options.get("execution_authorization_secret")
            or os.environ.get("BT_CTP_EXECUTION_AUTHORIZATION_SECRET")
            or ""
        )
        for private_option in (
            "execution_authorization_key_id",
            "execution_authorization_secret",
        ):
            self._config.pop(private_option, None)
            self._api_kwargs.pop(private_option, None)
        self._sdk_mode = self.provider == "btapi" and (
            (
                "exchange_kwargs" in sdk_options
                and (self.backend == "direct" or "forwarding_config" in sdk_options)
            )
            or (api is not None and callable(getattr(api, "poll_event", None)))
        )
        self._sdk_exchanges = dict(
            sdk_options.get("exchange_kwargs") or getattr(api, "exchange_kwargs", {}) or {}
        )
        self._sdk_routes = dict(sdk_options.get("symbol_routes") or {})
        configured_execution = sdk_options.get("execution_config")
        if isinstance(configured_execution, Mapping):
            self._sdk_execution_config = dict(configured_execution)
        else:
            self._sdk_execution_config = {
                key: sdk_options[key] for key in _SDK_EXECUTION_CONFIG_KEYS if key in sdk_options
            }
        self._sdk_require_account_risk = bool(sdk_options.get("require_account_risk", False))
        self._sdk_identity_bindings: Dict[str, Dict[str, Any]] = {}
        self._sdk_identity_fence_history: Dict[str, Tuple[int, int]] = {}
        self._sdk_identity_lock = threading.Lock()
        self._sdk_owned_api = api is None
        self._sdk_configured = False
        self._last_execution_summary = None
        self._last_account_risk_snapshot: Optional[Dict[str, Any]] = None
        self._last_account_risk_snapshot_generation: Optional[int] = None
        self._account_risk_lock = threading.Lock()
        self._account_risk_refresh_interval = max(
            float(sdk_options.get("account_risk_refresh_interval", 0.5)), 0.05
        )
        self._last_account_risk_refresh_requested = 0.0
        self._account_risk_refresh_pending = False
        funding_max_age = float(sdk_options.get("funding_max_age_seconds", 30.0))
        if not math.isfinite(funding_max_age) or funding_max_age < 0:
            raise ValueError("funding_max_age_seconds must be finite and nonnegative")
        funding_refresh_interval = float(
            sdk_options.get(
                "funding_refresh_interval_seconds",
                funding_max_age / 2.0 if funding_max_age else 0.0,
            )
        )
        if not math.isfinite(funding_refresh_interval) or funding_refresh_interval < 0:
            raise ValueError("funding_refresh_interval_seconds must be finite and nonnegative")
        self._funding_max_age_seconds = funding_max_age
        self._funding_refresh_interval_seconds = funding_refresh_interval
        self._funding_condition = threading.Condition(threading.RLock())
        self._funding_transport_lock = threading.Lock()
        self._funding_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._funding_last_errors: Dict[Tuple[str, str], str] = {}
        self._funding_last_requested: Dict[Tuple[str, str], float] = {}
        self._funding_queue: Deque[Tuple[int, Tuple[str, str], str, Any]] = collections.deque()
        self._funding_pending: set = set()
        self._funding_inflight_key: Optional[Tuple[str, str]] = None
        self._funding_direct_inflight = 0
        self._funding_worker_thread: Optional[threading.Thread] = None
        self._funding_generation = 0
        self._funding_accept_results = False
        self._funding_stop_requested = False
        self._funding_restart_blocked_by_worker = False
        self._funding_health: "collections.Counter[str]" = collections.Counter()
        self._sdk_client_refs: Dict[Tuple[str, str], Any] = {}
        self._sdk_venue_refs: Dict[Tuple[str, str], Any] = {}
        self._sdk_local_refs: Dict[str, Any] = {}
        queue_size = max(int(sdk_options.get("book_queue_size", 256)), 1)
        self._sdk_books: Dict[str, Any] = collections.defaultdict(
            lambda: collections.deque(maxlen=queue_size)
        )
        self._sdk_ticks: Dict[str, Any] = collections.defaultdict(
            lambda: collections.deque(maxlen=queue_size)
        )
        update_queue_size = max(int(sdk_options.get("broker_update_queue_size", 2048)), 1)
        self._sdk_updates: Deque[Any] = collections.deque(maxlen=update_queue_size)
        self._sdk_update_lock = threading.Lock()
        self._sdk_update_drop_records: Deque[Any] = collections.deque(
            maxlen=max(int(sdk_options.get("broker_update_drop_record_limit", 256)), 1)
        )
        # Newest-wins queues silently evict older books; count them per symbol
        # so reports can prove whether depth traffic was dropped.
        self._sdk_book_drops: Dict[str, int] = {}
        self._sdk_tick_drops: Dict[str, int] = {}
        self._sdk_update_drops = 0
        self._strategy_delivered_ids: Dict[str, collections.OrderedDict] = collections.defaultdict(
            collections.OrderedDict
        )
        self._feed_dropped_ids: Dict[str, collections.OrderedDict] = collections.defaultdict(
            collections.OrderedDict
        )
        self._strategy_delivery_id_limit = max(
            int(sdk_options.get("strategy_delivery_id_limit", 8192)), 1
        )
        self._market_drop_records: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(
                maxlen=max(int(sdk_options.get("market_drop_record_limit", 256)), 1)
            )
        )
        self._sdk_sequences: Dict[Tuple[str, str], int] = {}
        self._stream_health: Dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self._stream_state: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)
        self._stream_generation = 0
        self._sdk_event_batch_size = max(int(sdk_options.get("event_batch_size", 1024)), 1)
        configured_coalescing = sdk_options.get("coalesce_market_snapshots", ())
        if isinstance(configured_coalescing, str):
            configured_coalescing = (configured_coalescing,)
        self._sdk_coalesce_market_snapshots = tuple(configured_coalescing or ())

        self._command_queue_size = max(int(sdk_options.get("command_queue_size", 1024)), 1)
        requested_reserve = int(
            sdk_options.get(
                "command_reserved_capacity",
                max(8, self._command_queue_size // 10),
            )
        )
        self._command_reserved_capacity = min(
            max(requested_reserve, 0), max(self._command_queue_size - 1, 0)
        )
        self._command_shutdown_timeout = max(
            float(sdk_options.get("command_shutdown_timeout", 2.0)), 0.0
        )
        self._command_heap: List[Tuple[int, int, Dict[str, Any]]] = []
        self._command_sequence = itertools.count()
        self._command_condition = threading.Condition(threading.RLock())
        self._command_worker_thread: Optional[threading.Thread] = None
        self._command_worker_generation = 0
        self._command_generation = 0
        self._command_stop_requested = False
        self._command_accept_openings = not self._sdk_require_account_risk
        self._sdk_execution_arming = False
        # Set only immediately before a public CTP SDK arm call.  A failed
        # post-commit arm can leave the SDK leased while the local config still
        # says market-data-only, so shutdown must retain this fact until an
        # explicit public disarm or completed recovery proves revocation.
        self._ctp_sdk_arm_attempted = False
        self._accept_command_completions = False
        self._restart_blocked_by_worker = False
        self._restart_blocked_by_close = False
        self._sdk_close_thread: Optional[threading.Thread] = None
        self._sdk_close_generation = 0
        self._command_inflight = 0
        self._command_publications_pending = 0
        self._command_inflight_receipt_id: Optional[str] = None
        self._command_inflight_operation: Optional[str] = None
        self._command_health: "collections.Counter[str]" = collections.Counter()
        self._risk_state_lock = threading.Lock()
        self._risk_incident_epoch = 0
        self._last_risk_incident_reason = ""
        self._command_drop_records: Deque[Any] = collections.deque(
            maxlen=max(int(sdk_options.get("command_drop_record_limit", 256)), 1)
        )
        self._command_last_error = ""
        self._shutdown_state = "NOT_STARTED"
        self._sdk_command_types: Dict[str, Any] = {}
        self._cash = _coerce_float(cash)
        self._value = _coerce_float(value, self._cash)
        self._account_cache_ttl = max(_coerce_float(account_cache_ttl), 0.0)
        self._venue_balance_cache: Dict[str, Any] = {}
        self._last_venue_balance_refresh = 0.0
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
        self._tick_consumers: Dict[str, Any] = {}
        self._latest_ticks: Dict[str, Any] = {}
        self._latest_tick_lock = threading.Lock()
        self._ctp_query_lock = threading.RLock()
        query_interval = float(
            sdk_options.get(
                "ctp_query_min_interval_seconds",
                getattr(api, "ctp_query_min_interval_seconds", 1.0),
            )
        )
        if not math.isfinite(query_interval) or query_interval < 0:
            raise ValueError("ctp_query_min_interval_seconds must be finite and nonnegative")
        query_max_age = float(sdk_options.get("ctp_query_max_age_seconds", 30.0))
        if not math.isfinite(query_max_age) or query_max_age < 0:
            raise ValueError("ctp_query_max_age_seconds must be finite and nonnegative")
        self._ctp_query_min_interval_seconds = query_interval
        self._ctp_query_max_age_seconds = query_max_age
        self._ctp_query_last_started_monotonic: Optional[float] = None
        self._last_ctp_preflight_snapshot: Optional[Dict[str, Any]] = None
        self._last_ctp_bundle_preflight_snapshot: Optional[Dict[str, Any]] = None
        self._ctp_preflight_history: Deque[Dict[str, Any]] = collections.deque(maxlen=2)
        self._last_ctp_reconciliation_snapshot: Optional[Dict[str, Any]] = None
        self._ctp_execution_authorization: Optional[Dict[str, Any]] = None
        self._ctp_execution_authorization_sha256: Optional[str] = None
        self._ctp_execution_authorization_consumed = False
        self._ctp_execution_recovery: Optional[Dict[str, Any]] = None
        self._ctp_execution_recovery_proof: Optional[Dict[str, Any]] = None
        self._ctp_execution_recovery_armed = False
        self._ctp_execution_recovery_completed = False
        self._ctp_execution_recovery_cancel_requested = False
        self._ctp_execution_recovery_abort_result: Optional[Dict[str, Any]] = None
        self._ctp_execution_recovery_abort_lock = threading.Lock()
        self._ctp_execution_recovery_completion_lock = threading.RLock()
        self._ctp_execution_recovery_generation = 0
        self._ctp_execution_recovery_completion_pending = False
        self._ctp_execution_recovery_completion_receipt: Optional[Dict[str, Any]] = None
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

    @property
    def sdk_api(self) -> Any:
        """Return the managed SDK API object for governed public-method calls.

        The returned object is the single managed client this Store owns; the
        caller may only use it for the SDK's public contracts (approval
        contexts, redemptions, budget reservations) and must never construct a
        second native client.
        """
        return self._api

    @property
    def uses_async_commands(self) -> bool:
        """Return whether this SDK exposes the typed asynchronous command contract."""
        api = self._api
        return bool(
            self._sdk_mode
            and api is not None
            and all(
                inspect.iscoroutinefunction(getattr(api, name, None))
                for name in ("async_make_order", "async_cancel_order", "async_query_order")
            )
        )

    @property
    def requires_account_risk(self) -> bool:
        """Return whether startup must establish durable account-loss evidence."""
        return bool(self._sdk_mode and self._sdk_require_account_risk)

    def _require_async_sdk_commands(self) -> None:
        """Fail closed when an SDK trading session lacks any async operation."""
        if not self._sdk_mode:
            return
        missing = [
            name
            for name in ("async_make_order", "async_cancel_order", "async_query_order")
            if not inspect.iscoroutinefunction(getattr(self._api, name, None))
        ]
        if missing:
            raise BtApiStoreError(
                "SDK trading requires the complete asynchronous command contract: "
                + ", ".join(missing)
            )

    # Credential keys that must never appear in repr/str/logs in cleartext.
    _SENSITIVE_KEYS = frozenset(
        {
            "api_key",
            "api_secret",
            "access_token",
            "auth_code",
            "authorization",
            "credential",
            "credentials",
            "listen_key",
            "listenkey",
            "passphrase",
            "passwd",
            "password",
            "private_key",
            "public_key",
            "secret",
            "secret_key",
            "session_token",
            "signature",
            "token",
        }
    )
    _SENSITIVE_KEY_COMPACT = frozenset(key.replace("_", "") for key in _SENSITIVE_KEYS)

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
    def _is_sensitive_key(cls, key: Any) -> bool:
        """Return whether ``key`` conventionally names a credential value."""
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
        compact = normalized.replace("_", "")
        if normalized in cls._SENSITIVE_KEYS or compact in cls._SENSITIVE_KEY_COMPACT:
            return True

        return any(
            normalized.endswith(f"_{sensitive_key}") for sensitive_key in cls._SENSITIVE_KEYS
        )

    @classmethod
    def _masked_copy(cls, value: Any, _active: Optional[set[int]] = None) -> Any:
        """Build a cycle-safe diagnostic copy without invoking arbitrary repr methods."""
        if isinstance(value, BaseException):
            return type(value).__name__
        if isinstance(value, str):
            return _redact_diagnostic(value)
        if value is None or isinstance(value, (bool, int, float, Decimal)):
            return value

        active = set() if _active is None else _active
        identity = id(value)
        if identity in active:
            return "<recursive>"
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                return {
                    key: "***" if cls._is_sensitive_key(key) else cls._masked_copy(item, active)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [cls._masked_copy(item, active) for item in value]
            if isinstance(value, tuple):
                return tuple(cls._masked_copy(item, active) for item in value)
            if isinstance(value, set):
                return [cls._masked_copy(item, active) for item in value]
            if isinstance(value, frozenset):
                return tuple(cls._masked_copy(item, active) for item in value)
            if is_dataclass(value) and not isinstance(value, type):
                return cls._masked_copy(asdict(value), active)
            try:
                attributes = vars(value)
            except (TypeError, AttributeError):
                return type(value).__name__
            return {
                key: "***" if cls._is_sensitive_key(key) else cls._masked_copy(item, active)
                for key, item in attributes.items()
            }
        finally:
            active.discard(identity)

    @classmethod
    def _credential_values(
        cls,
        value: Any,
        sensitive_parent: bool = False,
        _active: Optional[set[int]] = None,
    ) -> set[str]:
        """Collect configured credential values for exact substring redaction."""
        result: set[str] = set()
        if sensitive_parent and isinstance(value, str):
            if len(value) >= 4:
                result.add(value)
            return result
        if value is None or isinstance(value, (str, bytes, bool, int, float, Decimal)):
            return result

        active = set() if _active is None else _active
        identity = id(value)
        if identity in active:
            return result
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    result.update(
                        cls._credential_values(
                            item,
                            sensitive_parent or cls._is_sensitive_key(key),
                            active,
                        )
                    )
                return result
            if isinstance(value, (list, tuple, set, frozenset)):
                for item in value:
                    result.update(cls._credential_values(item, sensitive_parent, active))
                return result
            if is_dataclass(value) and not isinstance(value, type):
                return cls._credential_values(asdict(value), sensitive_parent, active)
            try:
                attributes = vars(value)
            except (TypeError, AttributeError):
                return result
            return cls._credential_values(attributes, sensitive_parent, active)
        finally:
            active.discard(identity)

    @staticmethod
    def _replace_secret_values(value: Any, secret_values: Iterable[str]) -> Any:
        """Replace configured secret strings inside an already copied value."""
        if isinstance(value, Mapping):
            return {
                key: BtApiStore._replace_secret_values(item, secret_values)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [BtApiStore._replace_secret_values(item, secret_values) for item in value]
        if isinstance(value, tuple):
            return tuple(BtApiStore._replace_secret_values(item, secret_values) for item in value)
        if isinstance(value, set):
            return {BtApiStore._replace_secret_values(item, secret_values) for item in value}
        if isinstance(value, frozenset):
            return frozenset(
                BtApiStore._replace_secret_values(item, secret_values) for item in value
            )
        if isinstance(value, str):
            for secret in secret_values:
                value = value.replace(secret, "***")
        return value

    def redact_runtime_value(self, value: Any) -> Any:
        """Return a recursive, credential-safe copy for events and order diagnostics."""
        secrets = set()
        for source in (self._config, self._api_kwargs, self._sdk_exchanges):
            secrets.update(self._credential_values(source))
        if isinstance(value, BaseException):
            safe_args = [
                self._replace_secret_values(self._masked_copy(item), secrets) for item in value.args
            ]
            message = " ".join(str(item) for item in safe_args if item not in (None, ""))
            return message or type(value).__name__
        return self._replace_secret_values(self._masked_copy(value), secrets)

    def sanitize_exception(self, exc: BaseException) -> BaseException:
        """Redact exception args and attached diagnostic fields in place."""
        try:
            exc.args = tuple(self.redact_runtime_value(item) for item in exc.args)
        except Exception:
            pass
        try:
            for key, value in vars(exc).items():
                setattr(exc, key, self.redact_runtime_value(value))
        except Exception:
            pass
        return exc

    @classmethod
    def _mask_sensitive(cls, mapping: Optional[Mapping[Any, Any]]) -> Dict[Any, Any]:
        """Return a recursive copy with sensitive credential values masked.

        Use this whenever store kwargs/config need to be logged or surfaced for
        debugging so that secrets inside nested provider configuration are
        never written out in cleartext. Mappings, lists, and tuples are copied;
        the input object is not modified.
        """
        return cls._masked_copy(mapping or {})

    @staticmethod
    def _safe_exception_code(exc: Exception, default: str) -> str:
        """Return a bounded error identifier without copying vendor text or URLs."""
        value = getattr(exc, "code", None)
        if value in (None, ""):
            return default
        text = str(value).strip()
        if not text or len(text) > 128:
            return default
        if not all(character.isalnum() or character in "._:-" for character in text):
            return default
        return text

    def _force_sdk_market_data_only(
        self,
        reason: str,
        *,
        clear_authorization: bool = False,
    ) -> None:
        """Revoke any SDK write lease and retain only market-data capability."""
        ctp_unarmed = not (
            self._ctp_sdk_arm_attempted
            or self._sdk_execution_config.get("market_data_only") is not True
            or self._ctp_execution_recovery_armed
        )
        self._sdk_execution_config["market_data_only"] = True
        self._ctp_execution_recovery_armed = False
        with self._command_condition:
            self._command_accept_openings = False
        if clear_authorization:
            self._ctp_execution_authorization = None
            self._ctp_execution_authorization_sha256 = None
            self._ctp_execution_authorization_consumed = False
        api = self._api
        disarm = getattr(api, "disarm_execution", None) if api is not None else None
        # CTP's SDK disarm prepares an account stream even if the session was
        # never armed.  At ordinary Store shutdown, a fresh read-only CTP
        # session therefore needs no disarm; an actual arm attempt, recovery
        # arm, or non-read-only local state still requires revocation.  Other
        # fail-closed transitions retain their existing explicit disarm.
        skip_unarmed_ctp_stop_disarm = (
            str(reason or "") == "store_stop" and self._is_ctp_session_provider() and ctp_unarmed
        )
        if callable(disarm) and not skip_unarmed_ctp_stop_disarm:
            try:
                disarm(str(reason or "store_market_data_only"))
            except Exception as exc:
                self.sanitize_exception(exc)
                self._command_last_error = self._safe_exception_code(exc, "execution_disarm_failed")
            else:
                self._ctp_sdk_arm_attempted = False

    def _prepare_sdk_execution_authorization(self, reason: str) -> Dict[str, Any]:
        """Enter a reusable read-only state without revoking the next arm.

        ``disarm_execution`` is an irreversible fence for the current SDK
        generation.  Authorization preparation therefore uses the distinct
        public SDK transition and refuses to emulate it for older clients.
        """
        self._sdk_execution_config["market_data_only"] = True
        with self._command_condition:
            self._command_accept_openings = False
        api = self._ensure_api_ready()
        prepare = getattr(api, "prepare_execution_authorization", None)
        if not callable(prepare):
            raise BtApiStoreError(
                "Public SDK reusable execution-authorization preparation is unavailable"
            )
        try:
            result = prepare(reason=str(reason or "execution_authorization_reconfigured"))
        except Exception as exc:
            self.sanitize_exception(exc)
            raise BtApiStoreError("SDK execution-authorization preparation failed") from None
        if not isinstance(result, Mapping) or not (
            result.get("armed") is False
            and result.get("market_data_only") is True
            and result.get("reusable") is True
        ):
            raise BtApiStoreError("SDK execution-authorization preparation is not reusable")
        return dict(result)

    def _reset_ctp_session_evidence(self, reason: str, *, disarm: bool = True) -> None:
        """Discard evidence and authorization tied to an earlier CTP session."""
        with self._ctp_query_lock:
            self._last_ctp_preflight_snapshot = None
            self._last_ctp_bundle_preflight_snapshot = None
            self._last_ctp_reconciliation_snapshot = None
            self._ctp_preflight_history.clear()
            self._ctp_query_last_started_monotonic = None
            with self._command_condition:
                self._invalidate_ctp_execution_recovery_locked()
            if disarm:
                self._force_sdk_market_data_only(reason, clear_authorization=True)
            else:
                self._ctp_execution_authorization = None
                self._ctp_execution_authorization_sha256 = None
                self._ctp_execution_authorization_consumed = False

    def start(self, data=None, broker=None):
        """Start the store and attach broker/feed instances."""
        if data is not None and data not in self._data_feeds:
            self._data_feeds.append(data)

        if broker is not None:
            self._broker = broker

        if not self._started:
            self._prepare_funding_refresh_start()
            if not self._sdk_mode and self._restart_blocked_by_worker:
                worker = self._command_worker_thread
                if worker is not None and worker.is_alive():
                    raise BtApiStoreError(
                        "Cannot restart while the previous CTP query worker is still running"
                    )
                self._command_worker_thread = None
                self._restart_blocked_by_worker = False
                self._clear_sdk_updates("session_restart")
            # Query and quote evidence is scoped to one transport session.
            # A reconnect must establish fresh identity-bound snapshots before
            # either opening orders or shutdown pricing can use it.
            if self._is_ctp_session_provider():
                # Starting a read-only CTP Store must not call the SDK's
                # irreversible per-generation disarm.  The configured SDK
                # session is kept market-data-only until a later, freshly
                # verified authorization explicitly arms it.
                self._sdk_execution_config["market_data_only"] = True
                with self._command_condition:
                    self._command_accept_openings = False
                self._reset_ctp_session_evidence("store_start_clears_ctp_evidence", disarm=False)
            else:
                self._reset_ctp_session_evidence("store_start_clears_ctp_evidence", disarm=False)
            with self._latest_tick_lock:
                self._latest_ticks.clear()
            if self._sdk_mode:
                self._prepare_sdk_start()
                self._reset_sdk_stream_generation()
            self._ensure_api_ready()
            if self.uses_async_commands:
                # Resolve the optional SDK models during startup. Importing
                # bt_api_py lazily on the first order can otherwise add tens
                # of milliseconds to the Cerebro submission path.
                self._warm_sdk_command_types()
                with self._command_condition, self._risk_state_lock:
                    self._command_accept_openings = bool(
                        not self.requires_account_risk
                        and not self._command_health["risk_state_unknown"]
                    )
                self._shutdown_state = "RUNNING"
                self._start_command_worker()
            self._started = True
            self._begin_funding_refresh_generation()

    def _reset_sdk_stream_generation(self) -> None:
        """Discard every market-event identity from the previous SDK generation."""
        self._stream_generation += 1
        with self._account_risk_lock:
            self._last_account_risk_snapshot = None
            self._last_account_risk_snapshot_generation = None
            self._last_account_risk_refresh_requested = 0.0
            self._account_risk_refresh_pending = False
        with self._sdk_identity_lock:
            self._sdk_identity_bindings.clear()
        self._sdk_books.clear()
        self._sdk_ticks.clear()
        self._sdk_book_drops.clear()
        self._sdk_tick_drops.clear()
        self._sdk_sequences.clear()
        self._strategy_delivered_ids.clear()
        self._feed_dropped_ids.clear()
        self._market_drop_records.clear()
        self._stream_health.clear()
        self._stream_state.clear()

    def _prepare_sdk_start(self) -> None:
        """Reject restart while an earlier session worker can still mutate state."""
        close_thread = self._sdk_close_thread
        if close_thread is not None and close_thread.is_alive():
            self._restart_blocked_by_close = True
            raise BtApiStoreError(
                "Cannot restart while the previous SDK close callback is still running"
            )
        if close_thread is not None:
            self._sdk_close_thread = None
            self._restart_blocked_by_close = False

        worker = self._command_worker_thread
        if worker is not None and worker.is_alive():
            if self._restart_blocked_by_worker or self._command_stop_requested:
                raise BtApiStoreError(
                    "Cannot restart while the previous SDK command worker is still running"
                )
            return
        if worker is not None:
            self._command_worker_thread = None
        if not self._restart_blocked_by_worker:
            return

        # The old worker has now exited, so its session-local identities can be
        # discarded before a new generation is allowed to begin.
        self._restart_blocked_by_worker = False
        self._sdk_client_refs.clear()
        self._sdk_venue_refs.clear()
        self._sdk_local_refs.clear()
        self._sdk_books.clear()
        self._sdk_ticks.clear()
        self._sdk_sequences.clear()
        self._clear_sdk_updates("session_restart")
        self._sdk_configured = False
        if self._sdk_owned_api and self._api is not None:
            stale_api = self._api
            self._api = None
            close = getattr(stale_api, "close", None)
            if callable(close):
                closed, close_error, close_thread = self._bounded_call(
                    close, self._command_shutdown_timeout
                )
                self._sdk_close_thread = close_thread
                if not closed:
                    self._restart_blocked_by_close = True
                    self._command_health["close_timeouts"] += 1
                    self._shutdown_state = "INCOMPLETE"
                    raise BtApiStoreError(
                        "Cannot restart while the previous SDK close callback is still running"
                    )
                self._sdk_close_thread = None
                if close_error is not None:
                    self._command_health["close_failures"] += 1
                    self._command_last_error = self._safe_exception_code(
                        close_error, type(close_error).__name__
                    )
                    self._shutdown_state = "FAIL"

    def _prepare_funding_refresh_start(self) -> None:
        """Reject restart until a timed-out metadata reader has exited."""
        stale_owned_api = None
        with self._funding_condition:
            worker = self._funding_worker_thread
            if self._funding_direct_inflight:
                self._funding_restart_blocked_by_worker = True
                raise BtApiStoreError(
                    "Cannot restart while the previous funding refresh worker is still running"
                )
            if worker is not None and worker.is_alive():
                if self._funding_restart_blocked_by_worker or self._funding_stop_requested:
                    raise BtApiStoreError(
                        "Cannot restart while the previous funding refresh worker is still running"
                    )
                return
            if worker is not None:
                self._funding_worker_thread = None
            if self._funding_restart_blocked_by_worker:
                self._funding_restart_blocked_by_worker = False
                if self._sdk_owned_api and self._api is not None:
                    stale_owned_api = self._api
                    self._api = None
                    self._sdk_configured = False

        if stale_owned_api is not None:
            close = getattr(stale_owned_api, "close", None)
            if callable(close):
                closed, close_error, close_thread = self._bounded_call(
                    close, self._command_shutdown_timeout
                )
                self._sdk_close_thread = close_thread
                if not closed:
                    self._restart_blocked_by_close = True
                    self._shutdown_state = "INCOMPLETE"
                    raise BtApiStoreError(
                        "Cannot restart while the previous SDK close callback is still running"
                    )
                self._sdk_close_thread = None
                if close_error is not None:
                    self._shutdown_state = "FAIL"
                    raise BtApiStoreError("The previous SDK client could not be closed safely")

    def _begin_funding_refresh_generation(self) -> None:
        """Create an empty cache generation for the newly started Store session."""
        with self._funding_condition:
            self._funding_generation += 1
            self._funding_cache.clear()
            self._funding_last_errors.clear()
            self._funding_last_requested.clear()
            self._funding_queue.clear()
            self._funding_pending.clear()
            self._funding_inflight_key = None
            self._funding_stop_requested = False
            self._funding_accept_results = True
            self._funding_restart_blocked_by_worker = False
            self._funding_condition.notify_all()

    def freeze_openings(self, reason: str = "shutdown") -> None:
        """Reject future opening placements while preserving risk-reducing capacity."""
        with self._command_condition:
            self._command_accept_openings = False
        self.emit_runtime_event(
            "order_openings_frozen",
            status="frozen",
            details={"reason": str(reason)},
        )

    def latch_execution_evidence_loss(self, reason: str) -> Dict[str, Any]:
        """Freeze exposure after Broker detects a ledger-identity contradiction."""
        epoch = self._latch_risk_state_unknown(reason)
        rejected = self._reject_pending_openings_after_unknown(reason, reserve_publications=True)
        try:
            for completion in rejected:
                self._append_sdk_update(completion)
        finally:
            if rejected:
                with self._command_condition:
                    self._command_publications_pending -= len(rejected)
                    self._command_condition.notify_all()
        self.emit_runtime_event(
            "execution_evidence_lost",
            level="ERROR",
            status="frozen",
            error_code=str(reason),
            details={
                "risk_incident_epoch": epoch,
                "rejected_pending_openings": len(rejected),
            },
        )
        return {
            "risk_incident_epoch": epoch,
            "rejected_pending_openings": len(rejected),
            "accepting_openings": False,
        }

    def enable_openings_after_account_risk(self) -> Dict[str, Any]:
        """Unlock SDK openings only after a fresh identity-bound durable baseline."""
        if not self.requires_account_risk:
            self._enable_openings_after_safety_gate()
            return {"enabled": True, "account_risk_required": False}
        snapshot = self._read_account_risk_snapshot(self._ensure_api_ready())
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("durable") is not True
            or snapshot.get("trading_blocked") is not False
            or not snapshot.get("identity_binding_sha256")
        ):
            with self._command_condition:
                self._command_accept_openings = False
            raise BtApiStoreError("account_risk_baseline_not_proven")
        self._enable_openings_after_safety_gate()
        self.emit_runtime_event(
            "order_openings_enabled",
            status="enabled",
            details={"reason": "account_risk_baseline_proven"},
        )
        return {"enabled": True, "account_risk_required": True}

    def _enable_openings_after_safety_gate(self) -> None:
        """Enable openings only from one idle, conserved and reconciled state."""
        with self._sdk_update_lock, self._command_condition, self._risk_state_lock:
            ingress = self._command_health["broker_update_ingress"]
            delivered = self._command_health["broker_update_delivered"]
            dropped = self._command_health["broker_update_dropped"]
            update_depth = len(self._sdk_updates)
            if (
                self._command_health["risk_state_unknown"]
                or self._sdk_execution_arming
                or self._command_heap
                or self._command_inflight
                or self._command_publications_pending
                or update_depth
                or ingress != delivered + dropped + update_depth
            ):
                self._command_accept_openings = False
                raise BtApiStoreError("risk_state_reconcile_required")
            self._command_accept_openings = True

    def _start_funding_refresh_worker_locked(self) -> None:
        """Start the single read-only metadata worker while holding its condition."""
        worker = self._funding_worker_thread
        if worker is not None and worker.is_alive():
            return
        worker = threading.Thread(
            target=self._run_funding_refresh_worker,
            name=f"BtApiStoreFunding-{self.session_id}",
            daemon=True,
        )
        self._funding_worker_thread = worker
        worker.start()

    def _run_funding_refresh_worker(self) -> None:
        """Serialize funding reads independently of the order command worker."""
        current = threading.current_thread()
        try:
            while True:
                with self._funding_condition:
                    while not self._funding_queue and not self._funding_stop_requested:
                        self._funding_condition.wait(timeout=0.05)
                    if self._funding_stop_requested and not self._funding_queue:
                        return
                    generation, key, dataname, api = self._funding_queue.popleft()
                    if (
                        generation != self._funding_generation
                        or not self._funding_accept_results
                        or api is not self._api
                    ):
                        self._funding_pending.discard(key)
                        self._funding_health["stale_generation_results"] += 1
                        self._funding_condition.notify_all()
                        continue
                    self._funding_inflight_key = key
                    self._funding_health["dequeued"] += 1

                snapshot = None
                error = None
                try:
                    with self._funding_transport_lock:
                        with self._funding_condition:
                            can_read = bool(
                                generation == self._funding_generation
                                and self._funding_accept_results
                                and api is self._api
                            )
                        if can_read:
                            snapshot = self._read_funding_snapshot_from_api(api, dataname)
                except Exception as exc:
                    self.sanitize_exception(exc)
                    error = exc

                with self._funding_condition:
                    self._funding_pending.discard(key)
                    self._funding_inflight_key = None
                    if (
                        generation != self._funding_generation
                        or not self._funding_accept_results
                        or api is not self._api
                    ):
                        self._funding_health["stale_generation_results"] += 1
                    elif error is not None:
                        self._record_funding_refresh_error_locked(key, error, generation)
                    elif snapshot is not None:
                        self._publish_funding_snapshot_locked(key, snapshot, generation)
                    self._funding_condition.notify_all()
        finally:
            with self._funding_condition:
                if self._funding_worker_thread is current:
                    self._funding_worker_thread = None
                self._funding_inflight_key = None
                self._funding_condition.notify_all()

    def _signal_funding_refresh_stop(self) -> None:
        """Fence publications and discard metadata work that has not started."""
        with self._funding_condition:
            self._funding_accept_results = False
            self._funding_stop_requested = True
            while self._funding_queue:
                _generation, key, _dataname, _api = self._funding_queue.popleft()
                self._funding_pending.discard(key)
                self._funding_health["discarded_unsent"] += 1
            self._funding_condition.notify_all()

    def _stop_funding_refresh_worker(self, timeout: float) -> bool:
        """Wait a bounded interval for the read-only metadata worker."""
        self._signal_funding_refresh_stop()
        deadline = time.monotonic() + max(float(timeout), 0.0)
        with self._funding_condition:
            while self._funding_direct_inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._funding_health["worker_stop_timeouts"] += 1
                    self._funding_restart_blocked_by_worker = True
                    return False
                self._funding_condition.wait(timeout=remaining)
            worker = self._funding_worker_thread
        if worker is None:
            return True
        worker.join(max(deadline - time.monotonic(), 0.0))
        stopped = not worker.is_alive()
        with self._funding_condition:
            if stopped and self._funding_worker_thread is worker:
                self._funding_worker_thread = None
            if not stopped:
                self._funding_health["worker_stop_timeouts"] += 1
                self._funding_restart_blocked_by_worker = True
            self._funding_condition.notify_all()
        return stopped

    def _start_command_worker(self) -> None:
        """Start one daemon thread containing the SDK command asyncio worker."""
        worker = self._command_worker_thread
        if worker is not None and worker.is_alive():
            if self._restart_blocked_by_worker or self._command_stop_requested:
                raise BtApiStoreError(
                    "Cannot restart while the previous SDK command worker is still running"
                )
            return
        if self._restart_blocked_by_worker:
            self._prepare_sdk_start()
        self._command_stop_requested = False
        self._command_generation += 1
        generation = self._command_generation
        self._command_worker_generation = generation
        self._accept_command_completions = True
        worker = threading.Thread(
            target=self._run_command_worker,
            args=(generation,),
            name=f"BtApiStoreCommand-{self.session_id}",
            daemon=True,
        )
        self._command_worker_thread = worker
        worker.start()

    def _run_command_worker(self, generation: int) -> None:
        try:
            asyncio.run(self._command_worker(generation))
        except Exception as exc:
            self._command_health["worker_failures"] += 1
            self._command_last_error = self._safe_exception_code(exc, type(exc).__name__)
        finally:
            with self._command_condition:
                self._command_condition.notify_all()

    async def _command_worker(self, generation: int) -> None:
        """Execute prioritized SDK commands serially outside the Cerebro thread."""
        while True:
            with self._command_condition:
                while not self._command_heap and not self._command_stop_requested:
                    self._command_condition.wait(timeout=0.05)
                if self._command_stop_requested:
                    return
                _, _, command = heapq.heappop(self._command_heap)
                if command.get("session_generation") != generation:
                    self._record_command_drop_locked(command, "stale_session_generation")
                    continue
                if command.get("priority") == "open" and not self._command_accept_openings:
                    self._record_command_drop_locked(command, "openings_frozen_before_send")
                    completion = self._unsent_command_completion(
                        command, "openings_frozen_before_send"
                    )
                else:
                    completion = None
                if completion is not None:
                    self._command_health["dequeued"] += 1
                    self._command_publications_pending += 1
                else:
                    self._command_inflight += 1
                    self._command_inflight_receipt_id = command.get("receipt_id")
                    self._command_inflight_operation = command.get("operation")
                    self._command_health["dequeued"] += 1

            if completion is not None:
                try:
                    self._append_sdk_update(completion)
                finally:
                    with self._command_condition:
                        self._command_publications_pending -= 1
                        self._command_condition.notify_all()
                continue

            try:
                completion = await self._execute_sdk_command(command)
                rejected_openings = []
                if completion.get("execution_unknown") is True:
                    rejected_openings = self._reject_pending_openings_after_unknown(
                        "execution_unknown"
                    )
                self._append_sdk_update(completion)
                for rejected in rejected_openings:
                    self._append_sdk_update(rejected)
            finally:
                with self._command_condition:
                    self._command_inflight -= 1
                    if self._command_inflight_receipt_id == command.get("receipt_id"):
                        self._command_inflight_receipt_id = None
                        self._command_inflight_operation = None
                    self._command_condition.notify_all()

    def _record_command_drop_locked(self, command: Mapping[str, Any], reason: str) -> None:
        """Record identity for a command discarded while holding the queue lock."""
        priority = str(command.get("priority") or "unknown")
        self._command_health["discarded_unsent"] += 1
        self._command_health[f"discarded_{priority}"] += 1
        if priority != "open":
            self._command_health["risk_command_rejected"] += 1
            self._latch_risk_state_unknown(reason)
        if command.get("operation") == "account_risk":
            with self._account_risk_lock:
                self._account_risk_refresh_pending = False
        self._command_drop_records.append(
            {
                "reason": str(reason),
                "command": str(command.get("operation") or ""),
                "bt_order_ref": command.get("bt_order_ref"),
                "client_order_id": command.get("client_order_id"),
                "exchange_name": command.get("venue"),
                "session_generation": command.get("session_generation"),
            }
        )

    @staticmethod
    def _unsent_command_completion(command: Mapping[str, Any], reason: str) -> Dict[str, Any]:
        """Return an auditable terminal result for a command never sent remotely."""
        return {
            "kind": "command_completion",
            "command": command.get("operation"),
            "receipt_id": command.get("receipt_id"),
            "bt_order_ref": command.get("bt_order_ref"),
            "client_order_id": command.get("client_order_id"),
            "data_name": command.get("symbol"),
            "exchange_name": command.get("venue"),
            "priority": command.get("priority"),
            "session_generation": command.get("session_generation"),
            "success": False,
            "status": "rejected",
            "execution_unknown": False,
            "definite_reject": True,
            "terminal_confirmed": True,
            "remote_write_attempted": False,
            "error_code": str(reason),
            "error_msg": "Opening command was rejected locally before remote transport",
            "completed_monotonic_ns": time.monotonic_ns(),
        }

    def _reject_pending_openings_after_unknown(
        self, reason: str, *, reserve_publications: bool = False
    ) -> List[Dict[str, Any]]:
        """Freeze exposure and remove only unsent opening commands from the heap."""
        self.freeze_openings(reason)
        rejected = []
        with self._command_condition:
            retained = []
            while self._command_heap:
                item = heapq.heappop(self._command_heap)
                command = item[2]
                if command.get("priority") != "open":
                    retained.append(item)
                    continue
                self._record_command_drop_locked(command, "openings_frozen_after_unknown")
                rejected.append(
                    self._unsent_command_completion(command, "openings_frozen_after_unknown")
                )
            for item in retained:
                heapq.heappush(self._command_heap, item)
            if reserve_publications:
                # Reserve the publication window before releasing the queue
                # lock. Concurrent drain/stop callers must not close the update
                # channel between purging an opening and publishing its local
                # terminal rejection.
                self._command_publications_pending += len(rejected)
            self._command_condition.notify_all()
        return rejected

    def _latch_risk_state_unknown(self, reason: str) -> int:
        """Atomically freeze openings and advance the loss-of-evidence incident epoch."""
        with self._command_condition:
            self._command_accept_openings = False
            with self._risk_state_lock:
                self._risk_incident_epoch += 1
                self._command_health["risk_state_unknown"] = 1
                self._last_risk_incident_reason = str(reason)
                return self._risk_incident_epoch

    def _current_risk_incident_epoch(self) -> int:
        with self._risk_state_lock:
            return self._risk_incident_epoch

    def _invalidate_ctp_execution_recovery_locked(self) -> int:
        """Invalidate Store recovery state while holding the command condition."""
        self._ctp_execution_recovery_generation += 1
        self._ctp_execution_recovery = None
        self._ctp_execution_recovery_proof = None
        self._ctp_execution_recovery_armed = False
        self._ctp_execution_recovery_completed = False
        self._ctp_execution_recovery_cancel_requested = False
        self._ctp_execution_recovery_abort_result = None
        self._ctp_execution_recovery_completion_pending = False
        self._ctp_execution_recovery_completion_receipt = None
        return self._ctp_execution_recovery_generation

    def _clear_recovery_completion_pending_locked(self, receipt_id: Any) -> bool:
        """Clear only the matching recovery-completion claim under the queue lock."""
        receipt = self._ctp_execution_recovery_completion_receipt
        if not isinstance(receipt, Mapping) or receipt.get("receipt_id") != receipt_id:
            return False
        self._ctp_execution_recovery_completion_pending = False
        self._ctp_execution_recovery_completion_receipt = None
        return True

    def _discard_pending_commands_locked(self, reason: str) -> int:
        """Discard every command that has not begun network execution."""
        count = 0
        while self._command_heap:
            _, _, command = heapq.heappop(self._command_heap)
            self._record_command_drop_locked(command, reason)
            if command.get("operation") == "execution_recovery_complete":
                self._clear_recovery_completion_pending_locked(command.get("receipt_id"))
            count += 1
        return count

    def wait_for_commands(
        self, timeout: Optional[float] = None, *, stop_on_timeout: bool = False
    ) -> bool:
        """Wait a bounded interval for queued and in-flight SDK commands."""
        timeout = self._command_shutdown_timeout if timeout is None else max(float(timeout), 0.0)
        deadline = time.monotonic() + timeout
        with self._command_condition:
            while (
                self._command_heap or self._command_inflight or self._command_publications_pending
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._command_health["drain_timeouts"] += 1
                    if stop_on_timeout:
                        self._command_stop_requested = True
                        self._accept_command_completions = False
                        self._discard_pending_commands_locked("shutdown_deadline")
                        self._command_condition.notify_all()
                    return False
                self._command_condition.wait(timeout=remaining)
        return True

    def _stop_command_worker(self, timeout: float, *, discard_pending: bool = False) -> bool:
        with self._command_condition:
            self._command_stop_requested = True
            self._accept_command_completions = False
            if discard_pending:
                self._discard_pending_commands_locked("shutdown_deadline")
            self._command_condition.notify_all()
        worker = self._command_worker_thread
        if worker is None:
            return True
        worker.join(max(float(timeout), 0.0))
        stopped = not worker.is_alive()
        if stopped:
            self._command_worker_thread = None
        else:
            self._command_health["worker_stop_timeouts"] += 1
        return stopped

    @staticmethod
    def _bounded_call(
        callback, timeout: float
    ) -> Tuple[bool, Optional[BaseException], threading.Thread]:
        """Run a shutdown callback in a daemon thread and bound the caller's wait."""
        outcome: List[Optional[BaseException]] = [None]

        def invoke():
            try:
                callback()
            except BaseException as exc:  # preserve shutdown evidence without escaping the thread
                outcome[0] = exc

        thread = threading.Thread(target=invoke, name="BtApiStoreClose", daemon=True)
        thread.start()
        thread.join(max(float(timeout), 0.0))
        return not thread.is_alive(), outcome[0], thread

    def _bounded_sdk_close(self, api: Any, timeout: float) -> Tuple[bool, Optional[BaseException]]:
        """Close one SDK client within the caller's deadline and record the outcome."""
        close = getattr(api, "close", None)
        if not callable(close):
            close_error = BtApiStoreError("The SDK client does not expose close()")
            self._command_health["close_failures"] += 1
            self._command_last_error = type(close_error).__name__
            self._shutdown_state = "FAIL"
            return True, close_error

        closed, close_error, close_thread = self._bounded_call(close, timeout)
        self._sdk_close_generation = self._command_generation
        self._sdk_close_thread = close_thread
        if not closed:
            self._command_health["close_timeouts"] += 1
            self._shutdown_state = "INCOMPLETE"
            self._restart_blocked_by_close = True
        elif close_error is not None:
            self._sdk_close_thread = None
            self._command_health["close_failures"] += 1
            self._command_last_error = self._safe_exception_code(
                close_error, type(close_error).__name__
            )
            self._shutdown_state = "FAIL"
            self._restart_blocked_by_close = False
        else:
            self._sdk_close_thread = None
            self._restart_blocked_by_close = False
        return closed, close_error

    def stop(self, timeout: Optional[float] = None):
        """Bound command draining and disconnect the underlying client."""
        deadline = time.monotonic() + (
            self._command_shutdown_timeout if timeout is None else max(float(timeout), 0.0)
        )
        # Query and quote evidence is session-bound and becomes unusable as
        # soon as shutdown starts, even if disconnect later times out.
        self._reset_ctp_session_evidence("store_stop", disarm=False)
        with self._latest_tick_lock:
            self._latest_ticks.clear()
        self._signal_funding_refresh_stop()
        if self._sdk_mode and not self.uses_async_commands:
            return self._stop_synchronous_sdk(max(deadline - time.monotonic(), 0.0))
        self._venue_balance_cache = {}
        self._last_venue_balance_refresh = 0.0
        partial_owned_sdk = self._sdk_mode and self._sdk_owned_api and self._api is not None
        with self._command_condition:
            command_activity = bool(
                self._command_worker_thread is not None
                or self._command_heap
                or self._command_inflight
                or self._command_publications_pending
            )
        if (
            not self._connected
            and not self._started
            and not partial_owned_sdk
            and not command_activity
        ):
            return self.get_command_health()

        worker_stopped = True
        if self._sdk_mode:
            self.freeze_openings("store_stop")
        if command_activity:
            drained = self.wait_for_commands(
                max(deadline - time.monotonic(), 0.0), stop_on_timeout=True
            )
            worker_stopped = self._stop_command_worker(
                max(deadline - time.monotonic(), 0.0),
                discard_pending=not drained,
            )
            if not drained or not worker_stopped:
                self._shutdown_state = "INCOMPLETE"
            if not worker_stopped:
                self._restart_blocked_by_worker = True

        # Metadata I/O has its own lane, so a slow funding endpoint cannot
        # delay cancellation/close processing above. It must nevertheless
        # finish before the shared SDK object can be closed or reused.
        funding_worker_stopped = self._stop_funding_refresh_worker(
            max(deadline - time.monotonic(), 0.0)
        )
        if not funding_worker_stopped:
            self._shutdown_state = "INCOMPLETE"

        if self._sdk_mode and self._is_ctp_session_provider():
            self._force_sdk_market_data_only("store_stop", clear_authorization=True)

        try:
            if self._connected:
                self.emit_runtime_event("store_disconnect_requested", status="disconnecting")

            if self._api is not None and funding_worker_stopped:
                if self._sdk_mode:
                    self._cache_account_risk_snapshot_before_shutdown()
                    try:
                        if hasattr(self._api, "get_execution_summary"):
                            self._last_execution_summary = deepcopy(
                                self._api.get_execution_summary()
                            )
                    finally:
                        if worker_stopped:
                            self._bounded_sdk_close(
                                self._api,
                                max(deadline - time.monotonic(), 0.0),
                            )
                elif worker_stopped and hasattr(self._api, "disconnect"):
                    self._api.disconnect()
                elif worker_stopped and hasattr(self._api, "stop"):
                    self._api.stop()
        finally:
            if self._sdk_mode:
                # An owned SDK that failed while closing is in an unknown
                # transport state and must never be reused on a later start.
                if self._sdk_owned_api and worker_stopped and funding_worker_stopped:
                    self._api = None
                if worker_stopped and funding_worker_stopped:
                    self._sdk_configured = False
                    # These bindings and queues describe one in-memory SDK session.
                    self._sdk_client_refs.clear()
                    self._sdk_venue_refs.clear()
                    self._sdk_local_refs.clear()
                    self._sdk_books.clear()
                    self._sdk_ticks.clear()
                    self._clear_sdk_updates("store_stopped")
                    self._sdk_book_drops.clear()
                    self._sdk_tick_drops.clear()
                    self._sdk_sequences.clear()
                    if not self._restart_blocked_by_close and self._shutdown_state not in {
                        "INCOMPLETE",
                        "FAIL",
                    }:
                        self._shutdown_state = "PASS"
            elif worker_stopped:
                # Legacy/native CTP reconciliation uses the same worker even
                # though it is not an SDK execution session.
                self._clear_sdk_updates("store_stopped")
                if self._shutdown_state not in {"INCOMPLETE", "FAIL"}:
                    self._shutdown_state = "PASS"
            if not self._sdk_mode and not worker_stopped:
                # The CTP query still owns the legacy transport.  Preserve the
                # true connection state so a later restart reuses that session
                # instead of issuing a second connect against a live client.
                self.emit_runtime_event(
                    "store_disconnect_incomplete",
                    status="incomplete",
                    details={"reason": "ctp_query_worker_still_running"},
                )
            else:
                self._connected = False
            self._started = False
            self._subscribed_datanames.clear()
            self._tick_consumers.clear()
            if not self._connected:
                self.emit_runtime_event("store_disconnected", status="disconnected")
        return self.get_command_health()

    def _stop_synchronous_sdk(self, timeout: Optional[float] = None):
        """Preserve the pre-worker lifecycle for SDK-compatible fixture/legacy clients."""
        if self._is_ctp_session_provider():
            self._force_sdk_market_data_only("store_stop", clear_authorization=True)
        self._venue_balance_cache = {}
        self._last_venue_balance_refresh = 0.0
        self._sdk_client_refs.clear()
        self._sdk_venue_refs.clear()
        self._sdk_local_refs.clear()
        self._sdk_books.clear()
        self._sdk_ticks.clear()
        self._clear_sdk_updates("store_stopped")
        self._sdk_book_drops.clear()
        self._sdk_tick_drops.clear()
        funding_worker_stopped = self._stop_funding_refresh_worker(
            self._command_shutdown_timeout if timeout is None else timeout
        )
        partial_owned_sdk = self._sdk_owned_api and self._api is not None
        if not self._connected and not self._started and not partial_owned_sdk:
            return self.get_command_health()
        try:
            if self._connected:
                self.emit_runtime_event("store_disconnect_requested", status="disconnecting")
            if self._api is not None and funding_worker_stopped:
                self._cache_account_risk_snapshot_before_shutdown()
                try:
                    if hasattr(self._api, "get_execution_summary"):
                        self._last_execution_summary = deepcopy(self._api.get_execution_summary())
                finally:
                    self._bounded_sdk_close(self._api, timeout or 0.0)
        finally:
            if not funding_worker_stopped:
                self._shutdown_state = "INCOMPLETE"
            if self._sdk_owned_api and funding_worker_stopped:
                self._api = None
            if funding_worker_stopped:
                self._sdk_configured = False
                if not self._restart_blocked_by_close and self._shutdown_state not in {
                    "INCOMPLETE",
                    "FAIL",
                }:
                    self._shutdown_state = "PASS"
            self._connected = False
            self._started = False
            self._subscribed_datanames.clear()
            self._tick_consumers.clear()
            self.emit_runtime_event("store_disconnected", status="disconnected")
        return self.get_command_health()

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

    def set_source_stop_callback(self, callback) -> bool:
        """Register an optional fixture/source exhaustion callback.

        Live ``BtApi`` transports normally stop through broker/store lifecycle
        events. Deterministic replay clients may expose this small hook so a
        runner never reaches through the Store's private client attribute.
        """
        setter = getattr(self._api, "set_stop_callback", None)
        if not callable(setter):
            return False
        setter(callback)
        return True

    def get_cash(self) -> float:
        """Return cached available cash."""
        self.get_balance()
        return self._cash

    def get_value(self) -> float:
        """Return cached account value."""
        self.get_balance()
        return self._value

    def supports_position_mode(self, mode: str) -> bool:
        """Return whether this Store can represent the requested local position mode.

        This is a Backtrader ledger capability check.  The remote account's
        actual mode is queried separately through :meth:`get_account_config`;
        callers must validate that result before submitting live or demo orders.
        """
        mode = str(mode or "net").strip().lower()
        if mode != "dual_side":
            return True

        if self._sdk_mode:
            # The normalized SDK contract can retain explicit long/short legs.
            # It does not prove that the routed exchange account is configured
            # for dual-side execution; get_account_config provides that proof.
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
            if self._sdk_mode:
                balance = api.get_portfolio_balance(
                    venue_balances=self.get_venue_balances(force=force)
                )
            elif hasattr(api, "get_balance"):
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
            if self._sdk_mode:
                positions = []
                for venue in self._sdk_exchanges:
                    venue_positions = self._require_sdk_list_result(
                        api.get_position(venue, None, normalized=True),
                        "get_position",
                        venue,
                    )
                    for row in venue_positions:
                        item = dict(row)
                        amount = float(item["quantity"])
                        # Account snapshots may include every listed contract.
                        # Empty rows are not positions for the broker to hydrate.
                        if amount == 0.0:
                            continue
                        side = item["position_side"]
                        direction = ("short" if amount < 0 else "long") if side == "net" else side
                        item.update(
                            data_name=item["symbol"],
                            volume=abs(amount),
                            size=-abs(amount) if direction == "short" else abs(amount),
                            direction=direction,
                        )
                        positions.append(item)
            elif hasattr(api, "get_positions"):
                positions = api.get_positions()
            else:
                positions = []
        except AttributeError as exc:
            if self._sdk_mode or raise_errors:
                raise BtApiStoreError(
                    f"Failed to query positions through bt_api_py: {exc}"
                ) from exc
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

    def claim_tick_consumer(self, dataname: str, feed: Any) -> None:
        """Reserve a symbol's destructive tick cursor for one authoritative Feed."""
        key = str(dataname)
        owner = self._tick_consumers.get(key)
        if owner is not None and owner is not feed:
            raise BtApiStoreError(
                f"Live ticks for {key!r} already have an authoritative Feed consumer"
            )
        self._tick_consumers[key] = feed

    def release_tick_consumer(self, dataname: str, feed: Any) -> None:
        """Release a tick cursor only when it is still owned by *feed*."""
        key = str(dataname)
        if self._tick_consumers.get(key) is feed:
            self._tick_consumers.pop(key, None)

    def subscribe(self, dataname: str):
        """Subscribe to market data for the given symbol."""
        api = self._ensure_api_ready()
        dataname = str(dataname)

        if dataname in self._subscribed_datanames:
            return

        if hasattr(api, "subscribe"):
            if self._sdk_mode:
                venue = self._sdk_exchange(dataname)
                api.subscribe(f"{venue}___{dataname}", [{"topic": "depth", "symbol": dataname}])
            else:
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
            if self._sdk_mode:
                orders: List[Any] = []
                for venue in self._sdk_exchanges:
                    venue_orders = self._require_sdk_list_result(
                        api.get_open_orders(venue, None, normalized=True),
                        "get_open_orders",
                        venue,
                    )
                    orders.extend(self._sdk_broker_event(venue, row) for row in venue_orders)
            elif hasattr(api, "fetch_open_orders"):
                orders = api.fetch_open_orders()
            elif hasattr(api, "get_open_orders"):
                orders = api.get_open_orders()
            else:
                orders = []
        except AttributeError as exc:
            if self._sdk_mode or raise_errors:
                raise BtApiStoreError(
                    f"Failed to query open orders through bt_api_py: {exc}"
                ) from exc
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
        if self._sdk_mode:
            self._drain_sdk_events()
            bar = self._live_bars[dataname].popleft() if self._live_bars[dataname] else None
        elif hasattr(api, "poll_bar"):
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
        if self._sdk_mode:
            self._drain_sdk_events()
            tick = self._sdk_ticks[dataname].popleft() if self._sdk_ticks[dataname] else None
            if tick is not None:
                self._mark_feed_inflight(tick)
        elif hasattr(api, "poll_tick"):
            tick = api.poll_tick(dataname)
        elif hasattr(api, "get_next_tick"):
            tick = api.get_next_tick(dataname)
        else:
            tick = None
        if tick is not None:
            with self._latest_tick_lock:
                self._latest_ticks[dataname] = deepcopy(tick)
        return tick

    def get_latest_tick_snapshot(self, dataname: str):
        """Return the last consumed tick without issuing market-data I/O."""
        aliases = _contract_metadata_aliases(dataname)
        with self._latest_tick_lock:
            for alias in aliases:
                if alias in self._latest_ticks:
                    return deepcopy(self._latest_ticks[alias])
            alias_set = set(aliases)
            for key, tick in self._latest_ticks.items():
                if alias_set.intersection(_contract_metadata_aliases(key)):
                    return deepcopy(tick)
        return None

    def poll_orderbook(self, dataname: str):
        """Poll a single live orderbook snapshot from the API."""
        if not self._connected:
            return None

        api = self._ensure_api_ready()
        if self._sdk_mode:
            self._drain_sdk_events()
            book = self._sdk_books[dataname].popleft() if self._sdk_books[dataname] else None
            if book is not None:
                self._mark_feed_inflight(book)
            return book
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
        if self._sdk_mode:
            self._drain_sdk_events()
            return bool(self._sdk_ticks[dataname])
        if hasattr(api, "has_pending_tick"):
            return bool(api.has_pending_tick(dataname))

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return bool(live_ticks.get(dataname))

        return False

    def is_source_exhausted(self, dataname: str) -> bool:
        """Return explicit EOF for a finite fixture/replay source.

        Absence of the capability always means "still live".  Network clients
        therefore retain their existing idle behavior, while a deterministic
        source can let a feed end naturally after all buffered bars have been
        delivered.
        """

        if not self._connected:
            return False
        api = self._ensure_api_ready()
        method = getattr(api, "is_source_exhausted", None)
        return bool(method(dataname)) if callable(method) else False

    def get_source_event_time_watermark(self, dataname: str):
        """Return a finite source's final event-time watermark, if declared."""

        if not self._connected:
            return None
        api = self._ensure_api_ready()
        method = getattr(api, "get_source_event_time_watermark", None)
        return method(dataname) if callable(method) else None

    def has_pending_orderbook(self, dataname: str) -> bool:
        """Return whether the API has queued live orderbooks for a symbol."""
        if not self._connected:
            return False

        api = self._ensure_api_ready()
        if self._sdk_mode:
            self._drain_sdk_events()
            return bool(self._sdk_books[dataname])
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
        if self._sdk_mode:
            return dataname in self._sdk_routes or len(self._sdk_exchanges) == 1
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
        if self._sdk_mode:
            return dataname in self._sdk_routes or len(self._sdk_exchanges) == 1
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
        if self._sdk_mode:
            self._drain_sdk_events()
            with self._sdk_update_lock:
                update = self._sdk_updates.popleft() if self._sdk_updates else None
                if update is not None:
                    self._command_health["broker_update_delivered"] += 1
        elif hasattr(api, "poll_broker_update"):
            update = api.poll_broker_update()
        else:
            return None
        if update is None:
            return None

        if (
            self._sdk_mode
            and update.get("kind") == "command_completion"
            and update.get("command") == "reconcile"
            and update.get("success") is True
        ):
            self._maybe_clear_risk_state_latch(
                update.get("response"),
                incident_epoch=update.get("risk_incident_epoch_at_enqueue"),
                allow_current_reconcile_inflight=True,
                current_reconcile_receipt_id=update.get("receipt_id"),
            )

        update = self.redact_runtime_value(update)
        self._emit_broker_runtime_event(update)
        return update

    def _maybe_clear_risk_state_latch(
        self,
        snapshot: Any,
        *,
        incident_epoch: Optional[int],
        allow_current_reconcile_inflight: bool = False,
        current_reconcile_receipt_id: Optional[str] = None,
    ) -> bool:
        """Clear the active loss-of-evidence latch after a fully settled flat reconcile."""
        if type(incident_epoch) is not int or incident_epoch < 0:
            return False
        if not isinstance(snapshot, Mapping):
            return False
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("evidence_errors")
            or snapshot.get("trading_blocked") is not False
        ):
            return False
        configured = snapshot.get("configured_venues")
        reconciled = snapshot.get("reconciled_venues")
        if (
            type(configured) is not list
            or type(reconciled) is not list
            or not configured
            or len(configured) != len(set(configured))
            or sorted(configured) != sorted(reconciled)
        ):
            return False
        if type(snapshot.get("unknown_ids")) is not list or snapshot["unknown_ids"]:
            return False
        if type(snapshot.get("open_orders")) is not list or snapshot["open_orders"]:
            return False
        positions = snapshot.get("positions")
        if type(positions) is not list:
            return False
        for row in positions:
            if not isinstance(row, Mapping) or "quantity" not in row:
                return False
            try:
                quantity = float(row["quantity"])
            except (TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(quantity) or abs(quantity) > 1e-12:
                return False
        summary = snapshot.get("execution_summary")
        if not isinstance(summary, Mapping):
            return False
        if (
            type(summary.get("active_orders")) is not int
            or summary["active_orders"] != 0
            or summary.get("session_enabled") is not True
            or summary.get("trading_blocked") is not False
            or summary.get("evidence_complete") is not True
            or summary.get("evidence_errors")
            or type(summary.get("reconciliation_errors")) is not dict
            or summary["reconciliation_errors"]
        ):
            return False
        for key in ("unknown_ids", "fee_unresolved_orders", "funding_unresolved_orders"):
            value = summary.get(key)
            if type(value) is not list or value:
                return False
        generation = snapshot.get("generation")
        summary_generation = summary.get("generation")
        fencing_epoch = snapshot.get("fencing_epoch")
        summary_fencing_epoch = summary.get("fencing_epoch")
        if (
            type(generation) is not int
            or generation != self._command_generation
            or summary_generation != generation
            or type(fencing_epoch) is not int
            or fencing_epoch <= 0
            or summary_fencing_epoch != fencing_epoch
            or not snapshot.get("identity_binding_sha256")
            or snapshot.get("identity_binding_sha256") != summary.get("identity_binding_sha256")
        ):
            return False
        # Compare-and-clear under the single lock order used whenever update,
        # command and risk state must be viewed atomically. A reconcile that
        # began before a newer incident can never erase that incident.
        with self._sdk_update_lock, self._command_condition, self._risk_state_lock:
            update_depth = len(self._sdk_updates)
            ingress = self._command_health["broker_update_ingress"]
            delivered = self._command_health["broker_update_delivered"]
            dropped = self._command_health["broker_update_dropped"]
            current_inflight_is_reconcile = bool(
                allow_current_reconcile_inflight
                and self._command_inflight == 1
                and current_reconcile_receipt_id
                and self._command_inflight_receipt_id == current_reconcile_receipt_id
                and self._command_inflight_operation == "reconcile"
            )
            if (
                incident_epoch != self._risk_incident_epoch
                or generation != self._command_generation
                or self._command_heap
                or (self._command_inflight and not current_inflight_is_reconcile)
                or self._command_publications_pending
                or update_depth
                or ingress != delivered + dropped + update_depth
            ):
                return False
            self._command_health["risk_state_unknown"] = 0
            return True

    def _append_sdk_update(self, update: Dict[str, Any]) -> None:
        """Append a broker update and expose any bounded-queue loss."""
        safe_update = self.redact_runtime_value(dict(update))
        with self._sdk_update_lock:
            self._command_health["broker_update_ingress"] += 1
            if safe_update.get("kind") == "command_completion":
                generation = safe_update.get("session_generation")
                if not self._accept_command_completions:
                    self._record_sdk_update_drop_locked(safe_update, "session_not_accepting")
                    return
                if generation != self._command_generation:
                    self._record_sdk_update_drop_locked(safe_update, "stale_session_generation")
                    return
            if (
                self._sdk_updates.maxlen is not None
                and len(self._sdk_updates) >= self._sdk_updates.maxlen
            ):
                evicted = self._sdk_updates.popleft()
                self._record_sdk_update_drop_locked(evicted, "broker_update_queue_overflow")
            self._sdk_updates.append(safe_update)

    def _record_sdk_update_drop_locked(self, update: Mapping[str, Any], reason: str) -> None:
        """Record a dropped update identity while holding ``_sdk_update_lock``."""
        details = update.get("details") if isinstance(update.get("details"), Mapping) else {}
        self._sdk_update_drops += 1
        self._command_health["broker_update_dropped"] += 1
        self._latch_risk_state_unknown(reason)
        if reason in {"session_not_accepting", "stale_session_generation"}:
            self._command_health["late_completion_dropped"] += 1
        self._sdk_update_drop_records.append(
            self.redact_runtime_value(
                {
                    "reason": str(reason),
                    "kind": str(update.get("kind") or ""),
                    "command": str(update.get("command") or ""),
                    "bt_order_ref": update.get("bt_order_ref") or details.get("bt_order_ref"),
                    "client_order_id": update.get("client_order_id")
                    or details.get("client_order_id"),
                    "exchange_name": update.get("exchange_name") or details.get("exchange_name"),
                    "event_id": update.get("event_id") or details.get("event_id"),
                    "session_generation": update.get("session_generation"),
                }
            )
        )

    def _clear_sdk_updates(self, reason: str) -> int:
        """Drop queued broker updates with auditable conservation counters."""
        with self._sdk_update_lock:
            count = 0
            while self._sdk_updates:
                self._record_sdk_update_drop_locked(self._sdk_updates.popleft(), reason)
                count += 1
            return count

    def _enqueue_sdk_command(
        self,
        command: Dict[str, Any],
        *,
        priority_name: str,
        emit_event: bool = True,
    ) -> Dict[str, Any]:
        """Insert one command without waiting for transport or the SDK worker."""
        priority = _COMMAND_PRIORITY[priority_name]
        is_opening = priority_name == "open"
        receipt_id = uuid.uuid4().hex
        command.update(
            receipt_id=receipt_id,
            priority=priority_name,
            enqueued_monotonic_ns=time.monotonic_ns(),
        )
        if priority_name == "reconcile":
            command["risk_incident_epoch_at_enqueue"] = self._current_risk_incident_epoch()
        with self._command_condition:
            command["session_generation"] = self._command_generation
            depth = len(self._command_heap)
            opening_limit = self._command_queue_size - self._command_reserved_capacity
            rejection = ""
            if is_opening and not self._command_accept_openings:
                rejection = "openings_frozen"
            elif is_opening and depth >= opening_limit:
                rejection = "command_queue_reserved_capacity"
            elif depth >= self._command_queue_size:
                rejection = "command_queue_full"
            elif (
                self._command_stop_requested
                or self._restart_blocked_by_worker
                or self._restart_blocked_by_close
            ):
                rejection = "command_worker_stopping"

            if rejection:
                self._command_health["rejected"] += 1
                self._command_health[f"rejected_{priority_name}"] += 1
                if not is_opening:
                    self._command_health["risk_command_rejected"] += 1
                    self._latch_risk_state_unknown(rejection)
                receipt = {
                    "kind": "command_receipt",
                    "command": command["operation"],
                    "receipt_id": receipt_id,
                    "bt_order_ref": command.get("bt_order_ref"),
                    "client_order_id": command.get("client_order_id"),
                    "status": "rejected",
                    "queued": False,
                    "priority": priority_name,
                    "queue_depth": depth,
                    "error_code": rejection,
                    "error_msg": "SDK command queue cannot safely accept this command",
                }
            else:
                heapq.heappush(
                    self._command_heap,
                    (priority, next(self._command_sequence), command),
                )
                depth = len(self._command_heap)
                self._command_health["enqueued"] += 1
                self._command_health[f"enqueued_{priority_name}"] += 1
                self._command_health["max_queue_depth"] = max(
                    self._command_health["max_queue_depth"], depth
                )
                self._command_condition.notify()
                receipt = {
                    "kind": "command_receipt",
                    "command": command["operation"],
                    "receipt_id": receipt_id,
                    "bt_order_ref": command.get("bt_order_ref"),
                    "client_order_id": command.get("client_order_id"),
                    "status": "submitted",
                    "queued": True,
                    "priority": priority_name,
                    "queue_depth": depth,
                }

        if emit_event:
            self.emit_runtime_event(
                "sdk_command_queued" if receipt["queued"] else "sdk_command_rejected",
                level="INFO" if receipt["queued"] else "ERROR",
                status=receipt["status"],
                order_ref=command.get("bt_order_ref"),
                error_code=receipt.get("error_code", ""),
                error_msg=receipt.get("error_msg", ""),
                details={
                    "command": command["operation"],
                    "receipt_id": receipt_id,
                    "priority": priority_name,
                    "queue_depth": receipt["queue_depth"],
                },
            )
        return receipt

    def _is_sdk_market_data_only(self) -> bool:
        """Return whether the managed SDK session must reject every write."""
        return bool(self._sdk_mode and self._sdk_execution_config.get("market_data_only") is True)

    def _reject_market_data_only_command(
        self,
        operation: str,
        *,
        bt_order_ref: Any = None,
        client_order_id: Any = None,
    ) -> Dict[str, Any]:
        """Return a local rejection without creating or dispatching a command.

        Broker-level guards are useful for strategy code, but Store is also a
        public integration boundary. A caller holding a Store reference must
        not be able to enqueue a cancel or risk-reducing close while an SDK
        session is explicitly market-data-only.
        """
        receipt_id = uuid.uuid4().hex
        with self._command_condition:
            self._command_health["rejected"] += 1
            self._command_health["rejected_market_data_only"] += 1
            depth = len(self._command_heap)
        receipt = {
            "kind": "command_receipt",
            "command": operation,
            "receipt_id": receipt_id,
            "bt_order_ref": bt_order_ref,
            "client_order_id": client_order_id,
            "status": "rejected",
            "queued": False,
            "priority": "blocked",
            "queue_depth": depth,
            "error_code": "market_data_only",
            "error_msg": "SDK command is disabled for this market-data-only session",
        }
        self.emit_runtime_event(
            "sdk_command_rejected_local",
            level="ERROR",
            order_ref=bt_order_ref,
            error_code="market_data_only",
            error_msg="SDK command is disabled for this market-data-only session",
            status="rejected",
            details={"operation": operation},
        )
        return receipt

    async def _execute_sdk_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one typed SDK command and return a main-thread completion."""
        operation = command["operation"]
        request = command.get("request")
        recovery_submit = bool(
            operation == "submit" and getattr(request, "execution_role", None) == "recovery_exit"
        )
        completion = {
            "kind": "command_completion",
            "command": operation,
            "receipt_id": command["receipt_id"],
            "bt_order_ref": command.get("bt_order_ref"),
            "client_order_id": command.get("client_order_id"),
            "data_name": command.get("symbol"),
            "exchange_name": command.get("venue"),
            "priority": command["priority"],
            "session_generation": command.get("session_generation"),
            "risk_incident_epoch_at_enqueue": command.get("risk_incident_epoch_at_enqueue"),
            "completed_monotonic_ns": 0,
        }
        try:
            if operation == "reconcile":
                result = await asyncio.to_thread(self._sdk_reconcile_snapshot)
            elif operation == "ctp_reconcile":
                result = await asyncio.to_thread(
                    self.get_ctp_reconciliation_snapshot,
                    timeout=max(float(command.get("timeout") or 0.0), 0.0),
                )
            elif operation == "execution_recovery_complete":
                result = await asyncio.to_thread(
                    self._complete_queued_execution_recovery,
                    recovery_token_sha256=command["recovery_token_sha256"],
                    recovery_generation=command["recovery_generation"],
                )
            elif operation == "account_risk":
                result = await asyncio.to_thread(
                    self._read_account_risk_snapshot, self._ensure_api_ready()
                )
            else:
                result = await self._invoke_sdk_command(operation, command)
                if isinstance(result, Mapping):
                    event = dict(result)
                    event.setdefault("symbol", command.get("symbol"))
                    event.setdefault("client_order_id", command.get("client_order_id"))
                    result = self._sdk_broker_event(command["venue"], event)
            if isinstance(result, Mapping) and result.get("execution_unknown") is True:
                error_code = str(result.get("error_code") or "remote_execution_unknown")
                completion.update(
                    success=False,
                    status="unknown",
                    response=result,
                    execution_unknown=True,
                    remote_write_attempted=True,
                    definite_reject=False,
                    terminal_confirmed=False,
                    error_code=error_code,
                    error_msg="remote execution outcome is unknown",
                )
                self._command_health["failed"] += 1
                self._command_health["unknown"] += 1
                self._command_last_error = error_code
                self._latch_risk_state_unknown(error_code)
            else:
                completion.update(success=True, status="completed", response=result)
                self._command_health["completed"] += 1
        except asyncio.CancelledError:
            with self._command_condition:
                if operation == "execution_recovery_complete":
                    self._clear_recovery_completion_pending_locked(command.get("receipt_id"))
                if operation == "account_risk":
                    with self._account_risk_lock:
                        self._account_risk_refresh_pending = False
            raise
        except Exception as exc:
            self.sanitize_exception(exc)
            definite_reject = bool(getattr(exc, "definite_reject", False))
            # Once submit/cancel enters the SDK transport, an unclassified
            # exception cannot prove the venue did not act. Keep the original
            # identity alive and reconcile it. Only an explicit definite
            # rejection is safe to treat as terminal.
            execution_unknown = (
                bool(getattr(exc, "execution_unknown", False))
                or isinstance(exc, TimeoutError)
                or (operation in {"submit", "cancel"} and not definite_reject)
            )
            error_code = self._safe_exception_code(exc, type(exc).__name__)
            completion.update(
                success=False,
                status="unknown" if execution_unknown else "failed",
                execution_unknown=execution_unknown,
                remote_write_attempted=execution_unknown,
                definite_reject=definite_reject,
                terminal_confirmed=definite_reject,
                error_code=error_code,
                error_msg=(
                    "remote execution outcome is unknown"
                    if execution_unknown
                    else "SDK command failed"
                ),
            )
            self._command_health["failed"] += 1
            if execution_unknown:
                self._command_health["unknown"] += 1
                self._latch_risk_state_unknown(completion["error_code"])
            elif definite_reject and str(error_code).startswith("execution_arm_"):
                self._force_sdk_market_data_only(error_code, clear_authorization=False)
                self._latch_risk_state_unknown(error_code)
            self._command_last_error = completion["error_code"]
        if recovery_submit and completion.get("success") is not True:
            try:
                await asyncio.to_thread(
                    self.abort_execution_recovery,
                    "execution_recovery_dispatch_failed",
                )
            except Exception as exc:
                self.sanitize_exception(exc)
                completion["recovery_abort_error_code"] = self._safe_exception_code(
                    exc, "execution_recovery_abort_failed"
                )
        completion["completed_monotonic_ns"] = time.monotonic_ns()
        if operation == "execution_recovery_complete":
            with self._command_condition:
                self._clear_recovery_completion_pending_locked(command.get("receipt_id"))
        if operation == "account_risk":
            with self._account_risk_lock:
                self._account_risk_refresh_pending = False
        return completion

    async def _invoke_sdk_command(self, operation: str, command: Dict[str, Any]):
        if operation == "submit":
            self._validate_approval_lease_command(command)
        method_names = {
            "submit": "async_make_order",
            "cancel": "async_cancel_order",
            "query": "async_query_order",
        }
        async_name = method_names[operation]
        args = (command["venue"], command["request"])
        async_method = getattr(self._api, async_name, None)
        if not inspect.iscoroutinefunction(async_method):
            raise BtApiStoreError(f"SDK session does not expose coroutine {async_name}")
        # The SDK's managed write path requires the caller's opaque budget
        # reservation.  Pass it only when present so SDK facades and fakes
        # without the keyword keep their historical call shape.
        budget_capability = command.get("budget_capability")
        call_kwargs = {"normalized": True}
        if budget_capability is not None:
            call_kwargs["budget_capability"] = budget_capability
        result = async_method(*args, **call_kwargs)
        if not inspect.isawaitable(result):
            raise BtApiStoreError(f"SDK {async_name} did not return an awaitable")
        result = await result
        if not isinstance(result, Mapping):
            raise BtApiStoreError(f"SDK {async_name} did not return a normalized mapping")
        return dict(result)

    @staticmethod
    def _validate_approval_lease_command(command: Mapping[str, Any]) -> None:
        """Recheck an attached demo approval immediately before the SDK write."""
        fields = {
            "expires_at": command.get("approval_expires_at_utc"),
            "operation_count": command.get("approval_operation_count"),
            "maximum_count": command.get("approval_max_order_count"),
            "risk_reducing": command.get("approval_risk_reducing"),
        }
        if all(value is None for value in fields.values()):
            return
        if any(value is None for value in fields.values()):
            raise _ApprovalLeaseRejected("demo_approval_lease_incomplete")
        expires_at = fields["expires_at"]
        if not isinstance(expires_at, str) or not expires_at.endswith("Z"):
            raise _ApprovalLeaseRejected("demo_approval_expiry_invalid")
        try:
            parsed_expiry = _dt.datetime.fromisoformat(expires_at[:-1] + "+00:00")
        except ValueError:
            raise _ApprovalLeaseRejected("demo_approval_expiry_invalid") from None
        operation_count = fields["operation_count"]
        maximum_count = fields["maximum_count"]
        risk_reducing = fields["risk_reducing"]
        if (
            parsed_expiry.utcoffset() != _dt.timedelta(0)
            or isinstance(operation_count, bool)
            or not isinstance(operation_count, int)
            or operation_count <= 0
            or isinstance(maximum_count, bool)
            or not isinstance(maximum_count, int)
            or maximum_count <= 0
            or not isinstance(risk_reducing, bool)
        ):
            raise _ApprovalLeaseRejected("demo_approval_lease_invalid")
        if risk_reducing:
            return
        if operation_count > maximum_count:
            raise _ApprovalLeaseRejected("demo_approval_order_limit")
        if _dt.datetime.now(_dt.timezone.utc) >= parsed_expiry:
            raise _ApprovalLeaseRejected("demo_approval_expired")

    @staticmethod
    def _public_sdk_venue(venue: Any) -> str:
        """Return the stable provider key used by strategy-facing snapshots."""
        return str(venue or "").partition("___")[0].strip().lower()

    @staticmethod
    def _canonical_sdk_identity(identity: Mapping[str, Any]) -> Dict[str, Any]:
        """Normalize the non-secret fields which bind one SDK execution ledger."""
        result = {
            "provider": str(identity.get("provider") or "").strip().upper(),
            "environment": str(identity.get("environment") or "").strip().lower(),
            "account_id": str(identity.get("account_id") or "").strip().casefold(),
            "strategy_id": str(identity.get("strategy_id") or "").strip(),
        }
        fingerprint = str(identity.get("credential_fingerprint") or "").strip().lower()
        if fingerprint:
            result["credential_fingerprint"] = fingerprint
        return result

    @staticmethod
    def _require_sdk_list_result(result: Any, operation: str, venue: str) -> list:
        """Require the SDK's normalized collection contract without truthiness coercion."""
        if type(result) is not list:
            raise BtApiStoreError(f"sdk_{operation}_response_must_be_list:{venue}")
        return result

    def _validated_sdk_identity(self, venue: str, raw_identity: Any = None) -> Dict[str, Any]:
        """Validate, bind, and continuously fence one SDK-owned identity."""
        getter = getattr(self._api, "get_execution_identity", None)
        if raw_identity is None:
            if not callable(getter):
                raise BtApiStoreError("execution_identity_unavailable")
            try:
                raw_identity = getter(venue)
            except Exception as exc:
                self.sanitize_exception(exc)
                raise BtApiStoreError("execution_identity_unavailable") from None
        try:
            identity = _contract_mapping(raw_identity, f"execution identity for {venue}")
        except Exception as exc:
            self.sanitize_exception(exc)
            raise BtApiStoreError("execution_identity_invalid") from None

        exchange_name = identity.get("exchange_name")
        if exchange_name != venue:
            raise BtApiStoreError("execution_identity_venue_mismatch")
        canonical = self._canonical_sdk_identity(identity)
        missing = [
            key
            for key in ("provider", "environment", "account_id", "strategy_id")
            if not canonical[key]
        ]
        if missing:
            raise BtApiStoreError("identity_missing_" + "_".join(missing))
        expected_provider = self._public_sdk_venue(venue).upper()
        if canonical["provider"] != expected_provider:
            raise BtApiStoreError("execution_identity_provider_mismatch")

        required_environments = self._sdk_execution_config.get("required_environments") or {}
        expected_environment = (
            required_environments.get(venue) if isinstance(required_environments, Mapping) else None
        )
        if expected_environment in (None, ""):
            venue_config = self._sdk_exchanges.get(venue) or {}
            expected_environment = (
                venue_config.get("environment") if isinstance(venue_config, Mapping) else None
            )
        if (
            expected_environment not in (None, "")
            and canonical["environment"] != str(expected_environment).strip().lower()
        ):
            raise BtApiStoreError("execution_identity_environment_mismatch")

        expected_strategy = self._sdk_execution_config.get("strategy_id")
        if (
            expected_strategy not in (None, "")
            and canonical["strategy_id"] != str(expected_strategy).strip()
        ):
            raise BtApiStoreError("execution_identity_strategy_mismatch")

        account_aliases = self._sdk_execution_config.get("account_ids") or {}
        expected_alias = (
            account_aliases.get(venue) if isinstance(account_aliases, Mapping) else None
        )
        if expected_alias not in (None, ""):
            actual_alias = identity.get("account_alias")
            if (
                actual_alias in (None, "")
                or str(actual_alias).strip().casefold() != str(expected_alias).strip().casefold()
            ):
                raise BtApiStoreError("execution_identity_account_alias_mismatch")

        fingerprint = canonical.get("credential_fingerprint")
        if fingerprint and (
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise BtApiStoreError("execution_identity_fingerprint_invalid")
        actual_authority = str(identity.get("account_authority") or "").strip().lower()
        if fingerprint:
            if actual_authority != "credential_fingerprint":
                raise BtApiStoreError("execution_identity_account_authority_mismatch")
            derived_account_id = f"{expected_provider.lower()}-credential-{fingerprint}"
            if canonical["account_id"] != derived_account_id:
                raise BtApiStoreError("execution_identity_account_id_mismatch")
        elif (
            expected_provider == "CTP"
            and self._sdk_execution_config.get("market_data_only") is False
        ):
            if actual_authority != "account_fingerprint":
                raise BtApiStoreError("execution_identity_account_authority_mismatch")
            if re.fullmatch(r"acct_[0-9a-f]{16}", canonical["account_id"]) is None:
                raise BtApiStoreError("execution_identity_account_id_mismatch")
            actual_alias = str(identity.get("account_alias") or "").strip().casefold()
            if actual_alias != canonical["account_id"]:
                raise BtApiStoreError("execution_identity_account_alias_mismatch")
            if (
                expected_alias not in (None, "")
                and actual_alias != str(expected_alias).strip().casefold()
            ):
                raise BtApiStoreError("execution_identity_account_alias_mismatch")
        else:
            if self.backend == "direct" and expected_provider in {"BINANCE", "OKX"}:
                raise BtApiStoreError("execution_identity_fingerprint_missing")
            if expected_alias in (None, ""):
                raise BtApiStoreError("execution_identity_declared_account_id_missing")
            if actual_authority != "declared_account_id":
                raise BtApiStoreError("execution_identity_account_authority_mismatch")
            if canonical["account_id"] != str(expected_alias).strip().casefold():
                raise BtApiStoreError("execution_identity_account_id_mismatch")
        fencing_epoch = identity.get("fencing_epoch")
        if type(fencing_epoch) is not int or fencing_epoch <= 0:
            raise BtApiStoreError("execution_identity_fencing_epoch_invalid") from None

        binding = {**canonical, "fencing_epoch": fencing_epoch}
        identity_key = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        generation = int(self._stream_generation)
        with self._sdk_identity_lock:
            previous = self._sdk_identity_bindings.get(venue)
            if previous is not None and previous != binding:
                raise BtApiStoreError("execution_identity_changed_within_session")
            previous_fence = self._sdk_identity_fence_history.get(identity_key)
            if previous_fence is not None:
                previous_generation, previous_epoch = previous_fence
                if previous_generation == generation and previous_epoch != fencing_epoch:
                    raise BtApiStoreError("execution_identity_changed_within_session")
                if previous_generation != generation and fencing_epoch <= previous_epoch:
                    raise BtApiStoreError("execution_identity_fencing_epoch_not_advanced")
            self._sdk_identity_bindings[venue] = dict(binding)
            self._sdk_identity_fence_history[identity_key] = (generation, fencing_epoch)
        return {
            **identity,
            "provider": canonical["provider"],
            "environment": canonical["environment"],
            "account_id": str(identity.get("account_id") or "").strip(),
            "strategy_id": canonical["strategy_id"],
            "fencing_epoch": fencing_epoch,
            "exchange_name": venue,
        }

    @staticmethod
    def _sdk_identity_binding_sha256(identities: Mapping[str, Mapping[str, Any]]) -> str:
        """Hash the exact execution-identity vector without exposing credentials."""
        rows = []
        for venue, identity in sorted(identities.items()):
            canonical = BtApiStore._canonical_sdk_identity(identity)
            rows.append(
                {
                    "exchange_name": venue,
                    **canonical,
                    "fencing_epoch": int(identity.get("fencing_epoch") or 0),
                }
            )
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest() if rows else ""

    def _sdk_execution_evidence(self, raw_summary: Any):
        """Bind an SDK summary to this worker generation and durable fence."""
        summary = _contract_mapping(raw_summary, "execution session summary")
        errors = []
        identities = {}
        for venue in self._sdk_exchanges:
            try:
                identity = self._validated_sdk_identity(venue)
            except BtApiStoreError as exc:
                errors.append(f"{venue}:{exc}")
                continue
            identities[venue] = identity

        generation = int(self._command_generation or 0)
        if generation <= 0:
            errors.append("execution_generation_unavailable")
        raw_generation = summary.get("generation", summary.get("session_generation"))
        if raw_generation not in (None, ""):
            try:
                if int(raw_generation) != generation:
                    errors.append("execution_generation_mismatch")
            except (TypeError, ValueError):
                errors.append("execution_generation_invalid")

        fencing_epochs = set()
        for identity in identities.values():
            try:
                epoch = int(identity.get("fencing_epoch"))
            except (TypeError, ValueError):
                continue
            if epoch > 0:
                fencing_epochs.add(epoch)
        fencing_epoch = next(iter(fencing_epochs)) if len(fencing_epochs) == 1 else 0
        if fencing_epoch <= 0:
            errors.append("execution_fencing_epoch_unavailable")
        if len(fencing_epochs) > 1:
            errors.append("execution_fencing_epoch_mismatch")
        raw_fence = summary.get("fencing_epoch")
        if raw_fence not in (None, ""):
            try:
                if int(raw_fence) != fencing_epoch:
                    errors.append("execution_summary_fence_mismatch")
            except (TypeError, ValueError):
                errors.append("execution_summary_fence_invalid")

        if summary.get("evidence_complete") is False:
            errors.append("sdk_execution_evidence_incomplete")
        execution_is_armed = self._sdk_execution_config.get("market_data_only") is False
        sdk_evidence_errors = summary.get("evidence_errors")
        arm_error_codes = {
            str(value)
            for value in (sdk_evidence_errors if isinstance(sdk_evidence_errors, list) else ())
            if str(value).startswith("execution_arm_")
        }
        if execution_is_armed:
            if summary.get("armed") is not True:
                errors.append("execution_arm_not_armed")
            if summary.get("market_data_only") is not False:
                errors.append("execution_arm_market_data_only")
            if summary.get("arm_revoked") is not False:
                errors.append(str(summary.get("revocation_reason") or "execution_arm_revoked"))
            if arm_error_codes:
                errors.extend(sorted(arm_error_codes))
        if execution_is_armed and any(str(error).startswith("execution_arm_") for error in errors):
            self._force_sdk_market_data_only(
                "execution_arm_evidence_lost", clear_authorization=False
            )
            self._latch_risk_state_unknown("execution_arm_evidence_lost")
        identity_binding_sha256 = (
            self._sdk_identity_binding_sha256(identities)
            if len(identities) == len(self._sdk_exchanges)
            else ""
        )
        summary.update(
            generation=generation,
            session_generation=generation,
            fencing_epoch=fencing_epoch,
            as_of_monotonic_ns=time.monotonic_ns(),
            identity_binding_sha256=identity_binding_sha256,
            evidence_complete=not errors,
        )
        if errors:
            summary["trading_blocked"] = True
            summary["evidence_errors"] = sorted(set(errors))
        return summary, identities, errors

    @staticmethod
    def _sdk_position_snapshot_is_proven_zero(row: Any) -> bool:
        """Identify an empty synchronous position snapshot without hiding unknown state."""

        if (
            not isinstance(row, Mapping)
            or row.get("quantity_known") is not True
            or row.get("quantity_exact_zero") is not True
        ):
            return False
        quantity = row.get("quantity")
        if isinstance(quantity, bool) or quantity is None:
            return False
        try:
            parsed = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return parsed.is_finite() and parsed == 0

    @staticmethod
    def _sdk_account_risk_is_expected_prebaseline(snapshot: Any) -> bool:
        """Recognize only the SDK's clean first-start baseline-required latch."""

        if not isinstance(snapshot, Mapping):
            return False
        blocked_reasons = snapshot.get("blocked_reasons")
        evidence_errors = snapshot.get("evidence_errors")
        expected_blocked_reasons = {"account_evidence_incomplete", "baseline_missing"}
        expected_evidence_errors = {
            "account_risk_currency_mismatch",
            "account_risk_not_durable",
            "account_risk_trading_blocked",
            "invalid_baseline_equity",
            "invalid_baseline_equity_by_venue",
            "sdk_blocked_reasons_present",
            "sdk_evidence_incomplete",
        }
        return bool(
            snapshot.get("baseline_equity") is None
            and snapshot.get("baseline_equity_by_venue") is None
            and snapshot.get("loss_limit_breached") is False
            and snapshot.get("loss_breached_at") is None
            and snapshot.get("evidence_complete") is False
            and snapshot.get("durable") is False
            and snapshot.get("trading_blocked") is True
            and snapshot.get("error_code") == "account_risk_evidence_incomplete"
            and type(blocked_reasons) is list
            and len(blocked_reasons) == len(expected_blocked_reasons)
            and set(blocked_reasons) == expected_blocked_reasons
            and type(evidence_errors) is list
            and len(evidence_errors) == len(expected_evidence_errors)
            and set(evidence_errors) == expected_evidence_errors
        )

    def _sdk_reconcile_snapshot(self) -> Dict[str, Any]:
        positions = []
        open_orders: List[Any] = []
        reconciled_venues: List[str] = []
        for venue in self._sdk_exchanges:
            venue_positions = self._require_sdk_list_result(
                self._api.get_position(venue, None, normalized=True),
                "get_position",
                venue,
            )
            venue_open_orders = self._require_sdk_list_result(
                self._api.get_open_orders(venue, None, normalized=True),
                "get_open_orders",
                venue,
            )
            for row in venue_positions:
                if self._sdk_position_snapshot_is_proven_zero(row):
                    continue
                positions.append(
                    {
                        **dict(row),
                        "exchange_name": self._public_sdk_venue(venue),
                        "sdk_exchange_name": venue,
                    }
                )
            open_orders.extend(self._sdk_broker_event(venue, row) for row in venue_open_orders)
            # A venue is covered only after both risk-bearing reads returned.
            reconciled_venues.append(self._public_sdk_venue(venue))
        venue_balances = self._api.get_all_balances(normalized=True)
        balance = self._api.get_portfolio_balance(venue_balances=venue_balances)
        account_risk_snapshot = None
        account_risk_errors = []
        if self.requires_account_risk:
            # The SDK may require a current persisted-risk read before its
            # execution summary can prove the session clean. Read through the
            # same validated/cache-bound contract used by public risk queries.
            account_risk_snapshot = self._read_account_risk_snapshot(self._api)
            if not self._sdk_account_risk_is_expected_prebaseline(account_risk_snapshot):
                risk_error_code = account_risk_snapshot.get("error_code")
                if (
                    not isinstance(risk_error_code, str)
                    or not risk_error_code
                    or len(risk_error_code) > 128
                    or not all(
                        character.isalnum() or character in "._:-" for character in risk_error_code
                    )
                ):
                    risk_error_code = "evidence_incomplete"
                if account_risk_snapshot.get("evidence_complete") is not True:
                    account_risk_errors.append(f"account_risk:{risk_error_code}")
                if account_risk_snapshot.get("durable") is not True:
                    account_risk_errors.append("account_risk:not_durable")
                if account_risk_snapshot.get("trading_blocked") is not False:
                    account_risk_errors.append("account_risk:trading_blocked")
        get_execution_summary = getattr(self._api, "get_execution_summary", None)
        if not callable(get_execution_summary):
            raise BtApiStoreError("The SDK does not expose execution-session state")
        execution_summary, execution_identities, evidence_errors = self._sdk_execution_evidence(
            get_execution_summary()
        )
        evidence_errors.extend(account_risk_errors)

        unknown_ids = execution_summary.get("unknown_ids")
        if not isinstance(unknown_ids, (list, tuple, set, frozenset)):
            evidence_errors.append("execution_summary:unknown_ids_unproven")
            unknown_ids = []
        trading_blocked = execution_summary.get("trading_blocked")
        if not isinstance(trading_blocked, bool):
            evidence_errors.append("execution_summary:trading_blocked_unproven")
            trading_blocked = True
        configured_venues = sorted({self._public_sdk_venue(venue) for venue in self._sdk_exchanges})
        reconciled_venues = sorted(set(reconciled_venues))
        if set(reconciled_venues) != set(configured_venues):
            evidence_errors.append("venue_reconciliation_incomplete")
        ledger_partitions = {
            venue: {
                key: identity.get(key)
                for key in ("provider", "environment", "account_id", "strategy_id")
            }
            for venue, identity in execution_identities.items()
        }
        as_of_monotonic_ns = time.monotonic_ns()
        generation = int(execution_summary.get("generation") or 0)
        fencing_epoch = int(execution_summary.get("fencing_epoch") or 0)
        if account_risk_snapshot is not None:
            if account_risk_snapshot.get("fencing_epoch") != fencing_epoch:
                evidence_errors.append("account_risk:fencing_epoch_mismatch")
            if account_risk_snapshot.get("identity_binding_sha256") != execution_summary.get(
                "identity_binding_sha256"
            ):
                evidence_errors.append("account_risk:identity_binding_mismatch")
        evidence_errors = sorted(set(evidence_errors))
        result = {
            "positions": positions,
            "open_orders": open_orders,
            "venue_balances": venue_balances,
            "balance": balance,
            "configured_venues": configured_venues,
            "reconciled_venues": reconciled_venues,
            "execution_summary": execution_summary,
            "unknown_ids": list(unknown_ids),
            "trading_blocked": trading_blocked or bool(evidence_errors),
            "execution_identities": execution_identities,
            "identity_binding_sha256": execution_summary.get("identity_binding_sha256", ""),
            "ledger_partitions": ledger_partitions,
            "as_of": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "as_of_monotonic_ns": as_of_monotonic_ns,
            "generation": generation,
            "session_generation": generation,
            "fencing_epoch": fencing_epoch,
            "evidence_complete": not evidence_errors,
            "evidence_errors": evidence_errors,
        }
        if account_risk_snapshot is not None:
            result["account_risk_snapshot"] = account_risk_snapshot
        return result

    def enqueue_order(self, order) -> Dict[str, Any]:
        """Queue a typed SDK order and revoke recovery if dispatch cannot start."""

        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command(
                "submit",
                bt_order_ref=getattr(order, "ref", None),
            )

        info = getattr(order, "info", {})
        get_info = getattr(info, "get", lambda *_args: None)
        recovery_exit = get_info("execution_role") == "recovery_exit"
        try:
            receipt = self._enqueue_order_command(order)
        except Exception:
            if recovery_exit:
                self.abort_execution_recovery("execution_recovery_dispatch_failed")
            raise
        if recovery_exit and (
            not isinstance(receipt, Mapping) or receipt.get("queued") is not True
        ):
            self.abort_execution_recovery("execution_recovery_dispatch_failed")
        return deepcopy(receipt)

    def _enqueue_order_command(self, order) -> Dict[str, Any]:
        """Build and queue one typed SDK order."""
        self._ensure_api_ready()
        self._require_async_sdk_commands()
        self._start_command_worker()
        payload = self._order_to_payload(order)
        venue = self._sdk_exchange(payload["symbol"])
        request = self._sdk_order_request(venue, payload)
        client_id = request.client_order_id
        binding = self._sdk_client_refs.get((venue, str(client_id)), {})
        execution_contract = deepcopy(binding.get("execution_contract") or {})
        if hasattr(order, "addinfo"):
            order.addinfo(
                client_order_id=client_id,
                sdk_execution_contract=execution_contract,
                quantity_unit=execution_contract.get("quantity_unit"),
                position_mode=execution_contract.get("position_mode"),
            )
        elif isinstance(getattr(order, "info", None), dict):
            order.info["client_order_id"] = client_id
            order.info["sdk_execution_contract"] = execution_contract
            order.info["quantity_unit"] = execution_contract.get("quantity_unit")
            order.info["position_mode"] = execution_contract.get("position_mode")
        priority_name = (
            "close"
            if bool(payload.get("reduce_only"))
            or str(payload.get("offset") or "open").lower() != "open"
            else "open"
        )
        order_info = getattr(order, "info", {})
        approval_fields = {
            key: getattr(order_info, "get", lambda *_args: None)(key)
            for key in (
                "approval_expires_at_utc",
                "approval_operation_count",
                "approval_max_order_count",
                "approval_risk_reducing",
            )
        }
        budget_capability = getattr(order_info, "get", lambda *_args: None)("budget_capability")
        command = {
            "operation": "submit",
            "venue": venue,
            "symbol": payload["symbol"],
            "request": request,
            "bt_order_ref": payload.get("bt_order_ref"),
            "client_order_id": client_id,
            **approval_fields,
        }
        if budget_capability is not None:
            command["budget_capability"] = budget_capability
        receipt = self._enqueue_sdk_command(command, priority_name=priority_name)
        if not receipt["queued"]:
            binding = self._sdk_client_refs.pop((venue, str(client_id)), None)
            self._sdk_local_refs.pop(str(payload.get("bt_order_ref")), None)
            if binding is not None:
                for key, value in list(self._sdk_venue_refs.items()):
                    if value is binding:
                        self._sdk_venue_refs.pop(key, None)
        return receipt

    def enqueue_cancel(self, order_ref, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Queue a typed cancellation while preserving its reserved capacity."""
        if self._is_sdk_market_data_only():
            return self._reject_market_data_only_command(
                "cancel",
                bt_order_ref=order_ref,
            )
        self._ensure_api_ready()
        self._require_async_sdk_commands()
        self._start_command_worker()
        venue, request = self._sdk_cancel_request(order_ref, dataname)
        binding = self._sdk_local_refs.get(str(order_ref), {})
        return self._enqueue_sdk_command(
            {
                "operation": "cancel",
                "venue": venue,
                "symbol": request.symbol,
                "request": request,
                "bt_order_ref": binding.get("bt_order_ref", order_ref),
                "client_order_id": request.client_order_id,
            },
            priority_name="cancel",
        )

    def enqueue_query(self, order_ref, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Queue an order reconciliation query at the highest priority."""
        self._ensure_api_ready()
        self._require_async_sdk_commands()
        self._start_command_worker()
        venue, request, binding = self._sdk_query_request(order_ref, dataname)
        return self._enqueue_sdk_command(
            {
                "operation": "query",
                "venue": venue,
                "symbol": request.symbol,
                "request": request,
                "bt_order_ref": binding.get("bt_order_ref", order_ref),
                "client_order_id": request.client_order_id,
            },
            priority_name="query",
        )

    def enqueue_reconcile(self) -> Dict[str, Any]:
        """Queue a complete read-only position/open-order reconciliation."""
        self._ensure_api_ready()
        self._require_async_sdk_commands()
        self._start_command_worker()
        return self._enqueue_sdk_command(
            {"operation": "reconcile"},
            priority_name="reconcile",
        )

    def enqueue_ctp_reconciliation(self, *, timeout: float = 5.0) -> Dict[str, Any]:
        """Queue one complete CTP read round on the existing SDK command worker."""
        self._ensure_api_ready()
        if not self._is_ctp_session_provider() or not self.supports_complete_ctp_queries():
            return {
                "queued": False,
                "status": "rejected",
                "error_code": "ctp_query_capability_unavailable",
            }
        self._require_async_sdk_commands()
        self._start_command_worker()
        return self._enqueue_sdk_command(
            {
                "operation": "ctp_reconcile",
                "timeout": max(float(timeout), 0.0),
            },
            priority_name="reconcile",
        )

    def enqueue_execution_recovery_completion(
        self, *, recovery_token_sha256: str
    ) -> Dict[str, Any]:
        """Run the SDK-owned two-round recovery completion off the Cerebro thread."""
        token = self._require_sha256(recovery_token_sha256, "recovery_token_sha256")
        with self._ctp_execution_recovery_completion_lock:
            with self._command_condition:
                recovery = self._ctp_execution_recovery
                recovery_generation = self._ctp_execution_recovery_generation
                if (
                    self._ctp_execution_recovery_completion_pending
                    and isinstance(self._ctp_execution_recovery_completion_receipt, Mapping)
                    and isinstance(recovery, Mapping)
                    and token == recovery.get("recovery_token_sha256")
                ):
                    return deepcopy(self._ctp_execution_recovery_completion_receipt)
                recovery_can_complete = (
                    not self._ctp_execution_recovery_completed
                    and not self._ctp_execution_recovery_completion_pending
                    and isinstance(recovery, Mapping)
                    and (
                        (
                            recovery.get("status") == "RECOVERABLE"
                            and self._ctp_execution_recovery_armed
                            and recovery.get("allowed_actions") == ["close"]
                        )
                        or (
                            recovery.get("status") == "FLAT"
                            and not self._ctp_execution_recovery_armed
                            and recovery.get("allowed_actions") == ["complete"]
                        )
                    )
                )
                if not recovery_can_complete:
                    raise BtApiStoreError("SDK execution recovery is not completable")
                if token != recovery.get("recovery_token_sha256"):
                    raise BtApiStoreError("SDK execution recovery token mismatch")
            try:
                self._ensure_api_ready()
                self._require_async_sdk_commands()
                self._start_command_worker()
                with self._command_condition:
                    if (
                        recovery_generation != self._ctp_execution_recovery_generation
                        or self._ctp_execution_recovery is not recovery
                        or token != recovery.get("recovery_token_sha256")
                    ):
                        raise BtApiStoreError("SDK execution recovery plan became stale")
                    receipt = self._enqueue_sdk_command(
                        {
                            "operation": "execution_recovery_complete",
                            "recovery_token_sha256": token,
                            "recovery_generation": recovery_generation,
                        },
                        priority_name="reconcile",
                    )
                    if not isinstance(receipt, Mapping) or receipt.get("queued") is not True:
                        raise BtApiStoreError("SDK execution recovery completion was not queued")
                    self._ctp_execution_recovery_completion_pending = True
                    self._ctp_execution_recovery_completion_receipt = dict(receipt)
                return dict(receipt)
            except Exception:
                with self._command_condition:
                    receipt = self._ctp_execution_recovery_completion_receipt
                    if (
                        recovery_generation == self._ctp_execution_recovery_generation
                        and isinstance(receipt, Mapping)
                        and token == recovery.get("recovery_token_sha256")
                    ):
                        self._ctp_execution_recovery_completion_pending = False
                        self._ctp_execution_recovery_completion_receipt = None
                self._force_sdk_market_data_only(
                    "execution_recovery_completion_queue_failed",
                    clear_authorization=False,
                )
                raise

    def enqueue_account_risk_refresh(self) -> Dict[str, Any]:
        """Queue a non-blocking SDK account-risk refresh for strategy callbacks."""
        if not self.requires_account_risk:
            return {"queued": False, "status": "not_required"}
        if not self._started or not self._connected:
            return {"queued": False, "status": "store_not_running"}
        now = time.monotonic()
        with self._account_risk_lock:
            if self._account_risk_refresh_pending:
                return {"queued": True, "status": "already_pending"}
            if (
                self._last_account_risk_refresh_requested
                and now - self._last_account_risk_refresh_requested
                < self._account_risk_refresh_interval
            ):
                return {"queued": False, "status": "refresh_interval"}
            self._account_risk_refresh_pending = True
            self._last_account_risk_refresh_requested = now
        receipt = self._enqueue_sdk_command(
            {"operation": "account_risk"},
            priority_name="reconcile",
        )
        if receipt.get("queued") is not True:
            with self._account_risk_lock:
                self._account_risk_refresh_pending = False
        return receipt

    def get_command_health(self) -> Dict[str, Any]:
        """Return queue and worker health without exposing command payloads."""
        with self._command_condition:
            depth = len(self._command_heap)
            inflight = self._command_inflight
            publications_pending = self._command_publications_pending
            command_drop_records = list(self._command_drop_records)
        with self._sdk_update_lock:
            update_depth = len(self._sdk_updates)
            update_drop_records = list(self._sdk_update_drop_records)
        with self._risk_state_lock:
            risk_state_latched = bool(self._command_health["risk_state_unknown"])
            risk_incident_epoch = self._risk_incident_epoch
            last_risk_incident_reason = self._last_risk_incident_reason
        update_ingress = self._command_health["broker_update_ingress"]
        update_delivered = self._command_health["broker_update_delivered"]
        update_dropped = self._command_health["broker_update_dropped"]
        result = {
            **dict(self._command_health),
            "queue_capacity": self._command_queue_size,
            "reserved_capacity": self._command_reserved_capacity,
            "queue_depth": depth,
            "inflight": inflight,
            "publications_pending": publications_pending,
            "accepting_openings": self._command_accept_openings,
            "worker_alive": bool(
                self._command_worker_thread and self._command_worker_thread.is_alive()
            ),
            "last_error_code": self._command_last_error,
            "shutdown_state": self._shutdown_state,
            "session_generation": self._command_generation,
            "restart_blocked_by_worker": self._restart_blocked_by_worker,
            "close_thread_alive": bool(
                self._sdk_close_thread and self._sdk_close_thread.is_alive()
            ),
            "close_generation": self._sdk_close_generation,
            "restart_blocked_by_close": self._restart_blocked_by_close,
            "broker_update_queue_depth": update_depth,
            "broker_update_ingress": update_ingress,
            "broker_update_delivered": update_delivered,
            "broker_update_dropped": update_dropped,
            "risk_state_latched": risk_state_latched,
            "risk_incident_epoch": risk_incident_epoch,
            "last_risk_incident_reason": last_risk_incident_reason,
            "broker_update_conservation": (
                update_ingress == update_delivered + update_dropped + update_depth
            ),
            "command_drop_records": command_drop_records,
            "broker_update_drop_records": update_drop_records,
            "logging_errors": _LOGGING_HEALTH["logging_errors"],
        }
        funding_health = self.get_funding_refresh_health()
        result.update(
            {
                "funding_worker_alive": funding_health["worker_alive"],
                "funding_queue_depth": funding_health["queue_depth"],
                "funding_inflight": funding_health["inflight"],
                "funding_pending": funding_health["pending"],
                "funding_generation": funding_health["generation"],
                "funding_restart_blocked_by_worker": funding_health["restart_blocked_by_worker"],
                "funding_last_refresh_error": funding_health["last_refresh_error"],
            }
        )
        return result

    def submit_order(self, order):
        """Submit a backtrader order through the unified API."""
        if self._sdk_mode:
            if self._is_sdk_market_data_only():
                return self._reject_market_data_only_command(
                    "submit",
                    bt_order_ref=getattr(order, "ref", None),
                )
            self._ensure_api_ready()
            self._require_async_sdk_commands()
            return self.enqueue_order(order)
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
            self.sanitize_exception(exc)
            execution_unknown = bool(getattr(exc, "execution_unknown", False)) or isinstance(
                exc, TimeoutError
            )
            error_code = self._safe_exception_code(exc, type(exc).__name__)
            if self._sdk_mode:
                error_msg = (
                    "remote execution outcome is unknown"
                    if execution_unknown
                    else "remote order submission failed"
                )
            else:
                error_msg = str(exc)
            self.emit_runtime_event(
                "order_submit_unconfirmed" if execution_unknown else "order_reject_remote",
                level="WARNING" if execution_unknown else "ERROR",
                order_ref=order_ref,
                details=dict(payload),
                error_code=error_code,
                error_msg=error_msg,
                status="unconfirmed" if execution_unknown else "rejected",
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
        if self._sdk_mode:
            if self._is_sdk_market_data_only():
                return self._reject_market_data_only_command(
                    "cancel",
                    bt_order_ref=order_ref,
                )
            self._ensure_api_ready()
            self._require_async_sdk_commands()
            return self.enqueue_cancel(order_ref, dataname=dataname)
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
            self.sanitize_exception(exc)
            execution_unknown = bool(getattr(exc, "execution_unknown", False)) or isinstance(
                exc, TimeoutError
            )
            error_code = self._safe_exception_code(exc, type(exc).__name__)
            error_msg = (
                "remote cancellation outcome is unknown"
                if execution_unknown
                else ("remote cancellation failed" if self._sdk_mode else str(exc))
            )
            self.emit_runtime_event(
                "order_cancel_unconfirmed" if execution_unknown else "order_cancel_reject_remote",
                level="WARNING" if execution_unknown else "ERROR",
                order_ref=order_ref,
                details=details,
                error_code=error_code,
                error_msg=error_msg,
                status="unconfirmed" if execution_unknown else "rejected",
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
        safe_payload = self.redact_runtime_value(payload)
        self.put_notification("runtime_event", event=safe_payload)
        return safe_payload

    def _ctp_sdk_venues(self) -> Tuple[str, ...]:
        """Return explicitly configured CTP SDK routes without opening an adapter."""
        candidates = set(self._sdk_exchanges)
        candidates.update(self._sdk_routes.values())
        public_exchange_kwargs = getattr(self._api, "exchange_kwargs", None)
        if isinstance(public_exchange_kwargs, Mapping):
            candidates.update(public_exchange_kwargs)
        return tuple(
            sorted(
                {
                    str(venue).strip()
                    for venue in candidates
                    if str(venue).strip().partition("___")[0].upper() == "CTP"
                }
            )
        )

    def _ctp_sdk_exchange_name(self) -> str:
        venues = self._ctp_sdk_venues()
        if len(venues) != 1:
            raise BtApiStoreError("Exactly one configured CTP SDK exchange is required")
        return venues[0]

    def _is_ctp_session_provider(self) -> bool:
        if self.backend == "forwarding":
            return False
        provider = str(self.provider or "").strip().lower()
        if provider in {"ctp", "ctp_gateway"}:
            return True
        if provider == "btapi":
            return len(self._ctp_sdk_venues()) == 1
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
        if str(self.provider or "").strip().lower() == "btapi":
            getter = getattr(self._api, "get_ctp_session_state", None)
            if not callable(getter):
                return {}
            try:
                state = getter(exchange_name=self._ctp_sdk_exchange_name())
            except Exception as exc:
                _safe_log("debug", "Failed to read CTP SDK session state: %s", exc)
                return {}
            return dict(state) if isinstance(state, Mapping) else {}

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
                _safe_log("debug", "Failed to read CTP session state: %s", exc)
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

    def _ctp_query_targets(self) -> List[Any]:
        """Return bounded CTP query adapters, preferring one complete public surface."""
        if str(self.provider or "").strip().lower() == "btapi":
            # The SDK facade keeps execution-session ownership intact.  In
            # particular, do not call get_request_api() or inspect its feed
            # registry, both of which bypass the managed execution boundary.
            return [self._api] if callable(getattr(self._api, "query_ctp_result", None)) else []
        queue = [self._api]
        targets: List[Any] = []
        seen = set()
        while queue and len(targets) < 8:
            target = queue.pop(0)
            if target is None or id(target) in seen:
                continue
            seen.add(id(target))
            targets.append(target)
            for name in ("trader_client", "_trader", "_client", "feed"):
                nested = getattr(target, name, None)
                if nested is not None and id(nested) not in seen:
                    queue.append(nested)
        method_names = (
            "query_account_result",
            "query_positions_result",
            "query_orders_result",
            "query_trades_result",
            "query_instruments_result",
            "query_instrument_margin_rate_result",
            "query_instrument_commission_rate_result",
        )
        return sorted(
            targets,
            key=lambda item: sum(callable(getattr(item, name, None)) for name in method_names),
            reverse=True,
        )

    def supports_complete_ctp_queries(self, *, include_reference_data: bool = False) -> bool:
        """Report whether one adapter exposes the typed terminal-query contract."""
        if str(self.provider or "").strip().lower() == "btapi":
            return bool(
                len(self._ctp_sdk_venues()) == 1
                and callable(getattr(self._api, "query_ctp_result", None))
            )
        required = [
            "query_account_result",
            "query_positions_result",
            "query_orders_result",
            "query_trades_result",
        ]
        if include_reference_data:
            required.extend(
                [
                    "query_instruments_result",
                    "query_instrument_margin_rate_result",
                    "query_instrument_commission_rate_result",
                ]
            )
        return any(
            all(callable(getattr(target, name, None)) for name in required)
            for target in self._ctp_query_targets()
        )

    def _invoke_ctp_query(
        self,
        target: Any,
        request_type: str,
        method_name: str,
        *,
        timeout: float,
        kwargs: Mapping[str, Any],
    ) -> Any:
        """Invoke either the managed SDK facade or the legacy typed client."""
        if str(self.provider or "").strip().lower() == "btapi":
            method = getattr(target, "query_ctp_result", None)
            if not callable(method):
                raise BtApiStoreError("query_capability_unavailable")
            return method(
                self._ctp_sdk_exchange_name(),
                request_type,
                timeout=timeout,
                **dict(kwargs),
            )
        method = getattr(target, method_name, None)
        if not callable(method):
            raise BtApiStoreError("query_capability_unavailable")
        return method(timeout=timeout, **dict(kwargs))

    @staticmethod
    def _ctp_request_counts(session: Mapping[str, Any]) -> Optional[Dict[str, int]]:
        raw = session.get("request_counts")
        if not isinstance(raw, Mapping):
            return None
        if any(name not in raw for name in _CTP_WRITE_REQUEST_TYPES):
            return None
        counts: Dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            counts[str(key)] = value
        return counts

    @staticmethod
    def _ctp_request_count_delta(
        before: Optional[Mapping[str, int]], after: Optional[Mapping[str, int]]
    ) -> Optional[Dict[str, int]]:
        if before is None or after is None:
            return None
        keys = set(before) | set(after)
        if any(key not in before or key not in after for key in _CTP_WRITE_REQUEST_TYPES):
            return None
        delta = {key: after.get(key, 0) - before.get(key, 0) for key in sorted(keys)}
        if any(value < 0 for value in delta.values()):
            return None
        return delta

    @staticmethod
    def _normalise_ctp_instrument_row(row: Mapping[str, Any]) -> Dict[str, Any]:
        value = dict(row)
        aliases = {
            "instrument_id": "InstrumentID",
            "exchange_id": "ExchangeID",
            "product_id": "ProductID",
            "expire_date": "ExpireDate",
            "is_trading": "IsTrading",
            "price_tick": "PriceTick",
            "volume_multiple": "VolumeMultiple",
            "minimum_order_volume": "MinLimitOrderVolume",
            "lower_limit_price": "LowerLimitPrice",
            "upper_limit_price": "UpperLimitPrice",
            "open_interest": "OpenInterest",
            "volume": "Volume",
            "ranking_trading_day": "TradingDay",
        }
        for alias, raw_name in aliases.items():
            if alias not in value and value.get(raw_name) not in (None, ""):
                value[alias] = value[raw_name]
        return value

    @staticmethod
    def _ctp_query_record_to_public(record: Any) -> Dict[str, Any]:
        """Convert a typed/CTP record to a stable, credential-safe mapping."""
        if isinstance(record, Mapping):
            value = dict(record)
        elif is_dataclass(record):
            value = asdict(record)
        else:
            initializer = getattr(record, "init_data", None)
            if callable(initializer):
                try:
                    initialized = initializer()
                except Exception:
                    initialized = None
                if initialized is not None and initialized is not record:
                    return BtApiStore._ctp_query_record_to_public(initialized)
            value = {}
            for raw_name in ("order_info", "position_info", "account_info", "trade_info"):
                raw = getattr(record, raw_name, None)
                if isinstance(raw, Mapping):
                    value.update({key: raw[key] for key in _CTP_QUERY_RECORD_FIELDS if key in raw})
            all_data = getattr(record, "get_all_data", None)
            if callable(all_data):
                try:
                    public_data = all_data()
                except Exception:
                    public_data = None
                if isinstance(public_data, Mapping):
                    value.update(dict(public_data))
            value.update(_ctp_extract_fields(record, _CTP_QUERY_RECORD_FIELDS))
            getter_fields = {
                "order_id": "get_order_id",
                "client_order_id": "get_client_order_id",
                "order_size": "get_order_size",
                "order_price": "get_order_price",
                "side": "get_order_side",
                "status": "get_order_status",
                "offset": "get_order_offset",
                "exchange_id": "get_order_exchange_id",
                "executed_qty": "get_executed_qty",
                "instrument_id": "get_order_symbol_name",
            }
            for field, getter_name in getter_fields.items():
                getter = getattr(record, getter_name, None)
                if not callable(getter):
                    continue
                try:
                    item = getter()
                except Exception:
                    continue
                enum_value = getattr(item, "value", item)
                if enum_value not in (None, ""):
                    value[field] = enum_value
            if not value:
                raw = getattr(record, "__dict__", None)
                if isinstance(raw, dict):
                    value = {key: item for key, item in raw.items() if not key.startswith("_")}
        safe = _redact_diagnostic(value)
        return dict(safe) if isinstance(safe, Mapping) else {"record_type": type(record).__name__}

    @classmethod
    def _normalise_ctp_query_result(cls, result: Any, request_type: str) -> Dict[str, Any]:
        """Preserve explicit completion evidence; never infer success from an empty list."""
        if isinstance(result, Mapping):
            data = dict(result)
            nested = data.get("query_result")
            if isinstance(nested, Mapping):
                data = {
                    **{key: value for key, value in data.items() if key != "query_result"},
                    **dict(nested),
                }
            records = data.get("records")
        else:
            converter = getattr(result, "as_dict", None)
            if callable(converter):
                try:
                    data = dict(converter(include_records=False))
                except TypeError:
                    data = dict(converter())
            elif is_dataclass(result):
                data = asdict(result)
            else:
                data = {
                    key: getattr(result, key, None)
                    for key in (
                        "request_type",
                        "request_id",
                        "connection_generation",
                        "account_fingerprint",
                        "started_at_utc",
                        "completed_at_utc",
                        "is_last_seen",
                        "error_code",
                        "error_message",
                        "timed_out",
                        "complete",
                        "late_callback_count",
                        "unsupported",
                    )
                }
            records = getattr(result, "records", data.get("records"))
        records_schema_valid = isinstance(records, (list, tuple))
        if not records_schema_valid:
            records = ()
        data["records"] = [cls._ctp_query_record_to_public(row) for row in records]
        # The native layer seals provenance on ``QueryResult._source``; surface
        # its session facts so evidence validators can bind account/day/generation
        # without trusting caller-supplied strings.
        source = getattr(result, "_source", None)
        if source is not None:
            data.setdefault("trading_day", getattr(source, "trading_day", None))
            data.setdefault("schema_version", "backtrader.ctp.query-source.v1")
            data.setdefault("broker_id", getattr(source, "broker_id", None))
        data["expected_request_type"] = request_type
        actual_request_type = str(data.get("request_type") or "").strip().lower()
        data["expected_request_type"] = request_type
        data["request_type_matches"] = actual_request_type == request_type
        data["records_schema_valid"] = records_schema_valid
        data.setdefault("unsupported", False)
        data.setdefault("late_callback_count", 0)
        return data

    @staticmethod
    def _ctp_query_result_complete(result: Mapping[str, Any]) -> bool:
        error_code = result.get("error_code")
        try:
            request_id = int(result.get("request_id") or 0)
            generation = int(result.get("connection_generation") or 0)
        except (TypeError, ValueError):
            return False
        return bool(
            result.get("complete") is True
            and result.get("is_last_seen") is True
            and result.get("timed_out") is False
            and result.get("unsupported") is not True
            and error_code in (None, "", 0, "0")
            and result.get("completed_at_utc") not in (None, "")
            and request_id > 0
            and generation > 0
            and str(result.get("account_fingerprint") or "").strip()
            and result.get("request_type_matches") is True
            and result.get("records_schema_valid") is True
            and isinstance(result.get("records"), list)
        )

    @staticmethod
    def _ctp_query_failure(request_type: str, session: Mapping[str, Any], code: str):
        return {
            "request_type": request_type,
            "request_id": 0,
            "connection_generation": int(session.get("connection_generation") or 0),
            "account_fingerprint": str(session.get("account_fingerprint") or ""),
            "started_at_utc": _dt.datetime.now(_UTC).isoformat(),
            "completed_at_utc": None,
            "is_last_seen": False,
            "error_code": code,
            "error_message": code,
            "timed_out": "timeout" in str(code).lower() or "deadline" in str(code).lower(),
            "complete": False,
            "records": [],
            "expected_request_type": request_type,
            "request_type_matches": True,
            "records_schema_valid": True,
            "late_callback_count": 0,
            "unsupported": code == "query_capability_unavailable",
        }

    @staticmethod
    def _ctp_bundle_raw_text(value: Any, field_name: str) -> str:
        """Require one exact CTP wire identifier without normalising it.

        V1 preflight intentionally accepts user-friendly symbols and canonicalises
        them.  A bundle is different: its evidence is later useful for proving
        the exact native CTP identities of every leg, including DCE option IDs
        such as ``m2701-C-3400``.  This helper therefore only validates the raw
        field and never calls the V1 symbol canonicaliser.
        """
        if not isinstance(value, str) or not value or value != value.strip():
            raise BtApiStoreError(f"CTP bundle {field_name} must be non-empty exact text")
        return value

    @classmethod
    def _normalise_ctp_bundle_legs(
        cls,
        legs: Any,
        *,
        primary_leg: Any,
        primary_instrument_id: Any,
    ) -> List[Dict[str, Any]]:
        """Validate two or three exact raw CTP leg identities before I/O."""
        if isinstance(legs, (str, bytes, Mapping)):
            raise BtApiStoreError("CTP bundle legs must be an iterable of raw leg records")
        try:
            raw_legs = list(legs)
        except TypeError as exc:
            raise BtApiStoreError("CTP bundle legs must be an iterable of raw leg records") from exc
        if len(raw_legs) not in {2, 3}:
            raise BtApiStoreError("CTP bundle must contain exactly two or three legs")
        if primary_leg is not None and primary_instrument_id is not None:
            raise BtApiStoreError("CTP bundle primary selector is ambiguous")

        def _raw_pair(value: Any, *, allow_primary_flags: bool) -> Tuple[str, str, bool]:
            primary = False
            if isinstance(value, Mapping):
                exchange_values = [
                    value[name] for name in ("exchange_id", "ExchangeID") if name in value
                ]
                instrument_values = [
                    value[name] for name in ("instrument_id", "InstrumentID") if name in value
                ]
                if not exchange_values or not instrument_values:
                    raise BtApiStoreError("CTP bundle leg requires exchange_id and instrument_id")
                if any(value != exchange_values[0] for value in exchange_values[1:]) or any(
                    value != instrument_values[0] for value in instrument_values[1:]
                ):
                    raise BtApiStoreError("CTP bundle leg identity aliases are inconsistent")
                exchange_id, instrument_id = exchange_values[0], instrument_values[0]
                if allow_primary_flags:
                    primary_flags = []
                    for name in ("is_primary", "primary"):
                        if name not in value:
                            continue
                        flag = value[name]
                        if not isinstance(flag, bool):
                            raise BtApiStoreError(f"CTP bundle {name} must be boolean")
                        primary_flags.append(flag)
                    if len(set(primary_flags)) > 1:
                        raise BtApiStoreError("CTP bundle primary aliases are inconsistent")
                    primary = bool(primary_flags and primary_flags[0])
            elif isinstance(value, (tuple, list)) and len(value) == 2:
                exchange_id, instrument_id = value
            else:
                raise BtApiStoreError("CTP bundle leg must be a raw pair or mapping")

            exchange_id = cls._ctp_bundle_raw_text(exchange_id, "exchange_id")
            instrument_id = cls._ctp_bundle_raw_text(instrument_id, "instrument_id")
            if exchange_id not in _CTP_EXCHANGES:
                raise BtApiStoreError("CTP bundle exchange_id must use an exact CTP exchange code")
            if "." in instrument_id:
                raise BtApiStoreError("CTP bundle instrument_id must be a raw unqualified CTP ID")
            return exchange_id, instrument_id, primary

        parsed: List[Dict[str, Any]] = []
        seen = set()
        for value in raw_legs:
            exchange_id, instrument_id, primary = _raw_pair(value, allow_primary_flags=True)
            identity = (exchange_id, instrument_id)
            if identity in seen:
                raise BtApiStoreError("CTP bundle contains duplicate raw leg identities")
            seen.add(identity)
            parsed.append(
                {
                    "exchange_id": exchange_id,
                    "instrument_id": instrument_id,
                    "is_primary": primary,
                }
            )

        exchanges = {item["exchange_id"] for item in parsed}
        if len(exchanges) != 1:
            raise BtApiStoreError("CTP bundle legs must use one exact exchange_id")

        selected = {
            (item["exchange_id"], item["instrument_id"]) for item in parsed if item["is_primary"]
        }
        if primary_leg is not None:
            exchange_id, instrument_id, _unused = _raw_pair(primary_leg, allow_primary_flags=False)
            selected.add((exchange_id, instrument_id))
        if primary_instrument_id is not None:
            instrument_id = cls._ctp_bundle_raw_text(primary_instrument_id, "primary_instrument_id")
            if "." in instrument_id:
                raise BtApiStoreError(
                    "CTP bundle primary_instrument_id must be a raw unqualified CTP ID"
                )
            matches = {
                (item["exchange_id"], item["instrument_id"])
                for item in parsed
                if item["instrument_id"] == instrument_id
            }
            if len(matches) != 1:
                raise BtApiStoreError("CTP bundle primary_instrument_id must identify one leg")
            selected.update(matches)
        if len(selected) != 1:
            raise BtApiStoreError("CTP bundle requires exactly one primary leg")
        primary_identity = next(iter(selected))
        if primary_identity not in seen:
            raise BtApiStoreError("CTP bundle primary leg is not present in legs")
        for item in parsed:
            item["is_primary"] = (item["exchange_id"], item["instrument_id"]) == primary_identity
        return parsed

    @classmethod
    def _ctp_bundle_instrument_metadata(cls, row: Mapping[str, Any]) -> Dict[str, Any]:
        """Read CTP option/future fields without changing raw identity fields."""
        value = cls._normalise_ctp_instrument_row(row)

        def _text(*names: str) -> str:
            for name in names:
                raw = value.get(name)
                if raw not in (None, ""):
                    return str(raw).strip()
            return ""

        def _semantic_aliases(
            names: Tuple[str, ...], normalizer: Callable[[Any], Optional[str]]
        ) -> Tuple[Optional[str], str]:
            """Resolve same-meaning aliases without masking contradictory fields."""
            raw_values = [value[name] for name in names if value.get(name) not in (None, "")]
            if not raw_values:
                return None, "missing"
            normalized = [normalizer(raw) for raw in raw_values]
            if any(item is None for item in normalized):
                return None, "invalid"
            if len(set(normalized)) != 1:
                return None, "mismatch"
            return normalized[0], ""

        def _raw_identifier(*names: str) -> Tuple[str, str]:
            """Return a raw native ID without trimming its wire representation."""
            values = [value[name] for name in names if value.get(name) not in (None, "")]
            if not values:
                return "", "missing"
            first = values[0]
            if not isinstance(first, str):
                return "", "invalid"
            if not all(isinstance(item, str) and item == first for item in values[1:]):
                return "", "mismatch"
            return first, ""

        def _asset_type(raw: Any) -> Optional[str]:
            text = str(raw).strip().lower()
            return {
                "1": "future",
                "future": "future",
                "futures": "future",
                "2": "option",
                "option": "option",
                "options": "option",
            }.get(text)

        def _option_type(raw: Any) -> Optional[str]:
            text = str(raw).strip().lower()
            return {
                "1": "call",
                "call": "call",
                "c": "call",
                "2": "put",
                "put": "put",
                "p": "put",
            }.get(text)

        resolved_asset_type, asset_type_alias_error = _semantic_aliases(
            ("asset_type", "contract_type", "ProductClass", "product_class"), _asset_type
        )
        product_class = _text("ProductClass", "product_class")
        asset_type = resolved_asset_type or "unknown"
        option_type, option_type_alias_error = _semantic_aliases(
            ("option_type", "OptionsType", "options_type"), _option_type
        )
        raw_trading = value.get("is_trading", value.get("IsTrading"))
        if raw_trading in (True, 1, "1", b"1", "true", "TRUE"):
            is_trading: Optional[bool] = True
        elif raw_trading in (False, 0, "0", b"0", "false", "FALSE"):
            is_trading = False
        else:
            is_trading = None
        underlying_instrument_id, underlying_alias_error = _raw_identifier(
            "UnderlyingInstrID", "underlying_instrument", "underlying_instr_id"
        )
        strike_price, strike_numeric_error = cls._ctp_bundle_finite_numeric_aliases(
            value, ("strike_price", "StrikePrice")
        )
        return {
            "asset_type": asset_type,
            "asset_type_alias_error": asset_type_alias_error,
            "product_class": product_class,
            "option_type": option_type,
            "option_type_alias_error": option_type_alias_error,
            "underlying_instrument_id": underlying_instrument_id,
            "underlying_aliases_consistent": underlying_alias_error in {"", "missing"},
            "underlying_alias_error": underlying_alias_error,
            "strike_price": strike_price,
            "strike_numeric_error": strike_numeric_error,
            "expiry_date": _text("expiry_date", "ExpireDate", "expire_date"),
            "is_trading": is_trading,
        }

    @staticmethod
    def _ctp_bundle_valid_trading_day(value: Any) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{8}", text) is None:
            return ""
        try:
            _dt.datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return ""
        return text

    @staticmethod
    def _ctp_bundle_reference_match(
        rows: Iterable[Mapping[str, Any]],
        *,
        exchange_id: str,
        instrument_id: str,
        label: str,
        require_exchange: bool,
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """Require one exact result record and reject a broadened response."""
        matches: List[Dict[str, Any]] = []
        errors: List[str] = []

        def _identity_alias(
            candidate: Mapping[str, Any], names: Tuple[str, ...], alias_name: str
        ) -> Tuple[Any, List[str]]:
            values = [(name, candidate[name]) for name in names if name in candidate]
            if not values:
                return None, [f"{label}_response_{alias_name}_missing"]
            first = values[0][1]
            if any(value != first for _name, value in values[1:]):
                return None, [f"{label}_response_{alias_name}_alias_mismatch"]
            return first, []

        for row in rows:
            candidate = dict(row)
            raw_instrument_values = [
                candidate[name] for name in ("InstrumentID", "instrument_id") if name in candidate
            ]
            # CTP ReqQryInstrument may treat an instrument prefix as a
            # product query and return unrelated rows.  Those rows are not
            # identity evidence for this leg and must not poison an otherwise
            # exact response.  Once a row names the exact raw target, all
            # alias and exchange checks below remain strict.
            if raw_instrument_values and instrument_id not in raw_instrument_values:
                continue
            raw_instrument, instrument_errors = _identity_alias(
                candidate, ("InstrumentID", "instrument_id"), "instrument"
            )
            raw_exchange, exchange_errors = _identity_alias(
                candidate, ("ExchangeID", "exchange_id"), "exchange"
            )
            # Reference callbacks are permitted to omit an exchange entirely,
            # but a callback that supplies both aliases must still agree.  Do
            # not turn an identity conflict into a missing optional field.
            if not require_exchange and exchange_errors == [f"{label}_response_exchange_missing"]:
                exchange_errors = []
            errors.extend(instrument_errors)
            errors.extend(exchange_errors)
            if instrument_errors or exchange_errors:
                continue
            same_instrument = raw_instrument == instrument_id
            has_exchange = raw_exchange not in (None, "")
            same_exchange = raw_exchange == exchange_id
            if not same_instrument or (require_exchange and not same_exchange):
                errors.append(f"{label}_response_identity_mismatch")
                continue
            if has_exchange and not same_exchange:
                errors.append(f"{label}_response_exchange_mismatch")
                continue
            matches.append(candidate)
        if not matches:
            errors.append(f"{label}_record_missing")
        elif len(matches) != 1:
            errors.append(f"{label}_record_ambiguous")
        return (matches[0] if len(matches) == 1 else None), sorted(set(errors))

    @staticmethod
    def _ctp_bundle_finite_numeric_aliases(
        row: Mapping[str, Any], names: Tuple[str, ...]
    ) -> Tuple[Optional[float], Optional[str]]:
        """Read finite aliases, rejecting absent, malformed, and divergent values."""
        values = [row[name] for name in names if name in row]
        if not values:
            return None, "missing_or_invalid"
        parsed: List[float] = []
        for value in values:
            if value in (None, "") or isinstance(value, bool):
                return None, "missing_or_invalid"
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None, "missing_or_invalid"
            if not math.isfinite(number):
                return None, "missing_or_invalid"
            parsed.append(number)
        first = parsed[0]
        if any(candidate != first for candidate in parsed[1:]):
            return None, "alias_mismatch"
        return first, None

    @classmethod
    def _ctp_bundle_explicit_finite_number(
        cls, row: Mapping[str, Any], names: Tuple[str, ...]
    ) -> Optional[float]:
        """Compatibility wrapper for callers that only need a usable number."""
        number, error = cls._ctp_bundle_finite_numeric_aliases(row, names)
        return number if error is None else None

    @classmethod
    def _ctp_bundle_number_error(
        cls,
        row: Mapping[str, Any],
        names: Tuple[str, ...],
        *,
        label: str,
        field_name: str,
        positive: bool,
    ) -> Optional[str]:
        number, numeric_error = cls._ctp_bundle_finite_numeric_aliases(row, names)
        if numeric_error == "alias_mismatch":
            return f"{label}_{field_name}_alias_mismatch"
        if number is None:
            return f"{label}_{field_name}_missing_or_invalid"
        invalid_sign = number <= 0 if positive else number < 0
        if invalid_sign:
            return f"{label}_{field_name}_missing_or_invalid"
        return None

    @classmethod
    def _ctp_bundle_account_evidence_errors(cls, rows: List[Dict[str, Any]]) -> List[str]:
        """Require one usable account response; an empty account is never safe evidence."""
        if len(rows) != 1:
            return ["account_record_not_unique"]
        errors = []
        for names, field_name in (
            (("Balance", "balance"), "balance"),
            (("Available", "available"), "available"),
        ):
            error = cls._ctp_bundle_number_error(
                rows[0],
                names,
                label="account",
                field_name=field_name,
                positive=False,
            )
            if error:
                errors.append(error)
        return errors

    @classmethod
    def _ctp_bundle_instrument_evidence_errors(
        cls, row: Mapping[str, Any], *, label: str
    ) -> List[str]:
        errors = []
        for names, field_name in (
            (("PriceTick", "price_tick", "tick_size"), "price_tick"),
            (
                ("VolumeMultiple", "volume_multiple", "multiplier", "contract_size"),
                "volume_multiple",
            ),
            (
                ("MinLimitOrderVolume", "min_limit_order_volume", "minimum_order_volume"),
                "minimum_order_volume",
            ),
        ):
            error = cls._ctp_bundle_number_error(
                row,
                names,
                label=label,
                field_name=field_name,
                positive=True,
            )
            if error:
                errors.append(error)
        return errors

    @classmethod
    def _ctp_bundle_margin_evidence_errors(cls, row: Mapping[str, Any], *, label: str) -> List[str]:
        errors = []
        for names, field_name in (
            (("LongMarginRatioByMoney", "long_margin_ratio_by_money"), "margin_long_by_money"),
            (
                ("LongMarginRatioByVolume", "long_margin_ratio_by_volume"),
                "margin_long_by_volume",
            ),
            (("ShortMarginRatioByMoney", "short_margin_ratio_by_money"), "margin_short_by_money"),
            (
                ("ShortMarginRatioByVolume", "short_margin_ratio_by_volume"),
                "margin_short_by_volume",
            ),
        ):
            error = cls._ctp_bundle_number_error(
                row,
                names,
                label=label,
                field_name=field_name,
                positive=False,
            )
            if error:
                errors.append(error)
        return errors

    @classmethod
    def _ctp_bundle_commission_evidence_errors(
        cls, row: Mapping[str, Any], *, label: str
    ) -> List[str]:
        errors = []
        for names, field_name in (
            (
                ("OpenRatioByMoney", "open_ratio_by_money"),
                "commission_open_by_money",
            ),
            (
                ("OpenRatioByVolume", "open_ratio_by_volume"),
                "commission_open_by_volume",
            ),
            (
                ("CloseRatioByMoney", "close_ratio_by_money"),
                "commission_close_by_money",
            ),
            (
                ("CloseRatioByVolume", "close_ratio_by_volume"),
                "commission_close_by_volume",
            ),
            (
                ("CloseTodayRatioByMoney", "close_today_ratio_by_money"),
                "commission_close_today_by_money",
            ),
            (
                ("CloseTodayRatioByVolume", "close_today_ratio_by_volume"),
                "commission_close_today_by_volume",
            ),
        ):
            error = cls._ctp_bundle_number_error(
                row,
                names,
                label=label,
                field_name=field_name,
                positive=False,
            )
            if error:
                errors.append(error)
        return errors

    @classmethod
    def _ctp_bundle_option_trade_cost_evidence_errors(
        cls, row: Mapping[str, Any], *, label: str
    ) -> List[str]:
        errors = []
        for field_name in (
            "FixedMargin",
            "MiniMargin",
            "Royalty",
            "ExchFixedMargin",
            "ExchMiniMargin",
        ):
            error = cls._ctp_bundle_number_error(
                row,
                (field_name,),
                label=label,
                field_name=f"option_trade_cost_{field_name.lower()}",
                positive=False,
            )
            if error:
                errors.append(error)
        return errors

    @staticmethod
    def _ctp_bundle_parse_utc_timestamp(value: Any) -> Optional[_dt.datetime]:
        """Accept only a parseable, timezone-aware UTC query timestamp."""
        if isinstance(value, _dt.datetime):
            parsed = value
        elif isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                parsed = _dt.datetime.fromisoformat(text)
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() != _dt.timedelta(0):
            return None
        return parsed.astimezone(_UTC)

    @classmethod
    def _ctp_bundle_row_trading_day_errors(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        label: str,
        trading_day: str,
    ) -> List[str]:
        errors = []
        for row in rows:
            value = row.get("TradingDay", row.get("trading_day"))
            if value in (None, ""):
                continue
            row_day = cls._ctp_bundle_valid_trading_day(value)
            if not row_day or row_day != trading_day:
                errors.append(f"{label}_trading_day_mismatch")
        return sorted(set(errors))

    @staticmethod
    def _ctp_bundle_hash_safe(value: Any) -> Any:
        """Make a stable hash input even when a broken venue sends NaN."""
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else f"nonfinite:{value!r}"
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(key): BtApiStore._ctp_bundle_hash_safe(item)
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, (list, tuple)):
            return [BtApiStore._ctp_bundle_hash_safe(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = [BtApiStore._ctp_bundle_hash_safe(item) for item in value]
            return sorted(
                items,
                key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
            )
        return str(value)

    @staticmethod
    def _ctp_bundle_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
        """Hash stable bundle evidence while excluding capture clock fields."""
        material = {
            key: value
            for key, value in snapshot.items()
            if key not in {"captured_at_utc", "started_monotonic", "completed_monotonic"}
            and key != "snapshot_sha256"
        }
        return hashlib.sha256(
            json.dumps(
                BtApiStore._ctp_bundle_hash_safe(material),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def _reserve_ctp_query_slot(self, deadline: Optional[float]) -> Optional[float]:
        """Reserve one rate-limited query slot and return its remaining deadline."""
        now = time.monotonic()
        if self._ctp_query_last_started_monotonic is not None:
            due = self._ctp_query_last_started_monotonic + self._ctp_query_min_interval_seconds
            if deadline is not None and due >= deadline:
                return None
            if due > now:
                time.sleep(due - now)
                now = time.monotonic()
        if deadline is not None and now >= deadline:
            return None
        self._ctp_query_last_started_monotonic = now
        return max(deadline - now, 0.0) if deadline is not None else 0.0

    @staticmethod
    def _stable_ctp_query_rows(rows: Any) -> List[Dict[str, Any]]:
        values = [dict(row) for row in rows or () if isinstance(row, Mapping)]
        return sorted(
            values,
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str),
        )

    @classmethod
    def _ctp_order_row_is_active(cls, row: Mapping[str, Any]) -> bool:
        raw_status = row.get("status")
        status = str(raw_status or "").strip().lower()
        if not status:
            status = _normalize_ctp_order_status(
                row.get("OrderStatus"), row.get("OrderSubmitStatus"), "submitted"
            )
        if status in {
            "canceled",
            "cancelled",
            "completed",
            "filled",
            "rejected",
            "expired",
        }:
            return False
        remaining = row.get("remaining", row.get("VolumeTotal"))
        if remaining not in (None, ""):
            try:
                return float(remaining) > 0
            except (TypeError, ValueError):
                return True
        return True

    @staticmethod
    def _normalise_ctp_unmatched_trade_count(execution_summary: Any) -> Optional[int]:
        """Normalize the SDK's explicit empty states only.

        Some bt_api clients omit ``unmatched_trade_count`` while execution
        sessions are disabled or unarmed.  Only an explicit empty
        ``unknown_ids`` sequence — with the summary itself complete — makes
        that omission safely equivalent to zero; every other missing or
        malformed state remains unknown and fails closed.
        """
        if not isinstance(execution_summary, Mapping):
            return None
        if "unmatched_trade_count" in execution_summary:
            value = execution_summary["unmatched_trade_count"]
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        unknown_ids = execution_summary.get("unknown_ids")
        empty_unknown = (
            isinstance(unknown_ids, Sequence)
            and not isinstance(unknown_ids, (str, bytes, bytearray))
            and len(unknown_ids) == 0
        )
        if not empty_unknown:
            return None
        if execution_summary.get("session_enabled") is False:
            return 0
        # An unarmed market-data session with complete evidence and zero
        # unknown intents cannot hold unmatched trades; the omission is the
        # client's spelling of zero, not an unknown state.
        if (
            execution_summary.get("evidence_complete") is True
            and execution_summary.get("armed") is False
            and execution_summary.get("market_data_only") is True
            and int(execution_summary.get("active_orders") or 0) == 0
        ):
            return 0
        return None

    @staticmethod
    def _ctp_position_row_is_nonzero(row: Mapping[str, Any]) -> bool:
        for key in ("quantity", "size", "volume", "Position"):
            if row.get(key) in (None, ""):
                continue
            try:
                return abs(float(row[key])) > 1e-12
            except (TypeError, ValueError):
                return True
        return bool(row)

    def _build_ctp_query_snapshot(
        self,
        *,
        instrument_id: Optional[str],
        exchange_id: str,
        product_id: str,
        timeout: float,
        include_reference_data: bool,
        read_only: bool,
    ) -> Dict[str, Any]:
        if not self._is_ctp_session_provider():
            raise BtApiStoreError("CTP query snapshots require a CTP provider")
        # CTP's trade query has no ProductID field.  A product-level Stage A
        # therefore narrows trades to its configured exchange, while Stage B
        # narrows them further to the frozen instrument.  Positions and orders
        # intentionally remain account-wide: they are the safety evidence that
        # blocks an opening when any external exposure or active order exists.
        exchange_id = _coerce_text(exchange_id).upper()
        instrument_id = _coerce_text(instrument_id).upper() or None
        trade_query_scope = {
            "instrument_id": instrument_id or "",
            "exchange_id": exchange_id,
        }
        trade_query_kwargs = {name: value for name, value in trade_query_scope.items() if value}
        total_timeout = float(timeout)
        if not math.isfinite(total_timeout) or total_timeout < 0:
            raise ValueError("CTP query timeout must be finite and nonnegative")
        query_started_monotonic = time.monotonic()
        # ``timeout=0`` is retained as the existing immediate fixture/probe
        # mode. Positive values are one deadline for the entire query group,
        # never a fresh timeout for every individual request.
        deadline = query_started_monotonic + total_timeout if total_timeout > 0 else None
        self._ensure_api_ready()
        session_before = self._read_ctp_session_state()
        request_counts_before = self._ctp_request_counts(session_before)
        targets = self._ctp_query_targets()
        target = targets[0] if targets else None
        query_specs = [
            ("account", "query_account_result", {}),
            ("positions", "query_positions_result", {}),
            ("orders", "query_orders_result", {}),
            ("trades", "query_trades_result", trade_query_kwargs),
        ]
        if include_reference_data:
            # ``ProductID`` was added to the public CTP facade for the Stage A
            # product scan.  Do not pass an empty value through the legacy
            # direct-client signature: older compatible clients only accept
            # instrument/exchange filters, and Stage B already has the exact
            # frozen instrument constraint.  A nonempty Stage A ProductID is
            # deliberately retained so an implementation that cannot enforce
            # it reports an incomplete snapshot rather than broadening scope.
            instrument_query_kwargs = {
                "instrument_id": instrument_id or "",
                "exchange_id": exchange_id,
            }
            if product_id:
                instrument_query_kwargs["product_id"] = product_id
            query_specs.append(
                (
                    "instruments",
                    "query_instruments_result",
                    instrument_query_kwargs,
                )
            )
            if instrument_id:
                # Per-instrument fee/margin queries are Stage B evidence for
                # one frozen instrument.  A product or exchange scan has no
                # single instrument, so those queries are deliberately out of
                # scope there instead of failing placeholders that would
                # poison the product-scan Stage A evidence contract.
                query_specs.extend(
                    [
                        (
                            "margin_rate",
                            "query_instrument_margin_rate_result",
                            {"instrument_id": instrument_id, "exchange_id": exchange_id},
                        ),
                        (
                            "commission_rate",
                            "query_instrument_commission_rate_result",
                            {"instrument_id": instrument_id, "exchange_id": exchange_id},
                        ),
                    ]
                )

        query_results: Dict[str, Dict[str, Any]] = {}
        with self._ctp_query_lock:
            for name, method_name, kwargs in query_specs:
                if not method_name or target is None:
                    result = self._ctp_query_failure(
                        name,
                        session_before,
                        (
                            "instrument_id_required"
                            if not method_name
                            else "query_capability_unavailable"
                        ),
                    )
                else:
                    request_timeout = (
                        self._reserve_ctp_query_slot(deadline) if deadline is not None else 0.0
                    )
                    if request_timeout is None:
                        result = self._ctp_query_failure(
                            name, session_before, "query_deadline_exceeded"
                        )
                    else:
                        try:
                            result = self._normalise_ctp_query_result(
                                self._invoke_ctp_query(
                                    target,
                                    name,
                                    method_name,
                                    timeout=request_timeout,
                                    kwargs=kwargs,
                                ),
                                name,
                            )
                        except Exception as exc:
                            result = self._ctp_query_failure(
                                name, session_before, type(exc).__name__
                            )
                if name == "trades":
                    # Persist the requested server-side constraints with the
                    # terminal evidence.  The response is checked against this
                    # scope below rather than trusting the remote filter alone.
                    result["requested_scope"] = dict(trade_query_scope)
                query_results[name] = result

        session_after = self._read_ctp_session_state()
        request_counts_after = self._ctp_request_counts(session_after)
        request_count_delta = self._ctp_request_count_delta(
            request_counts_before, request_counts_after
        )
        session = session_after if session_after else session_before

        errors = [
            f"{name}_query_incomplete"
            for name, result in query_results.items()
            if not self._ctp_query_result_complete(result)
        ]
        for name, result in query_results.items():
            if result.get("request_type_matches") is not True:
                errors.append(f"{name}_request_type_mismatch")
            if result.get("records_schema_valid") is not True:
                errors.append(f"{name}_records_schema_invalid")
        generations = {
            int(result["connection_generation"])
            for result in query_results.values()
            if self._ctp_query_result_complete(result)
        }
        fingerprints = {
            str(result["account_fingerprint"])
            for result in query_results.values()
            if self._ctp_query_result_complete(result)
        }
        if len(generations) != 1:
            errors.append("query_generation_mismatch")
        if len(fingerprints) != 1:
            errors.append("query_account_fingerprint_mismatch")

        def _session_generation(value: Mapping[str, Any]) -> int:
            raw = value.get("connection_generation")
            if isinstance(raw, bool):
                return 0
            try:
                parsed = int(raw or 0)
            except (TypeError, ValueError):
                return 0
            return parsed if parsed > 0 else 0

        generation_before = _session_generation(session_before)
        generation_after = _session_generation(session_after)
        fingerprint_before = str(session_before.get("account_fingerprint") or "").strip()
        fingerprint_after = str(session_after.get("account_fingerprint") or "").strip()
        trading_day_before = str(session_before.get("trading_day") or "").strip()
        trading_day_after = str(session_after.get("trading_day") or "").strip()
        if generation_before <= 0 or generation_after <= 0:
            errors.append("session_generation_missing")
        elif generation_before != generation_after:
            errors.append("session_generation_changed")
        if fingerprint_before == "" or fingerprint_after == "":
            errors.append("session_account_fingerprint_missing")
        elif fingerprint_before != fingerprint_after:
            errors.append("session_account_fingerprint_changed")
        if trading_day_before == "" or trading_day_after == "":
            errors.append("session_trading_day_missing")
        elif trading_day_before != trading_day_after:
            errors.append("session_trading_day_changed")
        if generation_after > 0 and generations != {generation_after}:
            errors.append("query_generation_session_mismatch")
        if fingerprint_after and fingerprints != {fingerprint_after}:
            errors.append("query_account_fingerprint_session_mismatch")

        all_request_ids: Dict[str, int] = {}
        for name, result in query_results.items():
            raw_request_id = result.get("request_id")
            if isinstance(raw_request_id, bool):
                parsed_request_id = 0
            else:
                try:
                    parsed_request_id = int(raw_request_id or 0)
                except (TypeError, ValueError):
                    parsed_request_id = 0
            all_request_ids[name] = parsed_request_id
        positive_request_ids = [value for value in all_request_ids.values() if value > 0]
        if len(set(positive_request_ids)) != len(positive_request_ids):
            errors.append("query_request_id_not_unique")
        session_ready = bool(session.get("read_only_ready") is True or session.get("ready") is True)
        if not session_ready:
            errors.append("ctp_session_not_ready")
        auto_confirm = session.get(
            "auto_settlement_confirm",
            getattr(target, "auto_settlement_confirm", None) if target is not None else None,
        )
        write_request_free = bool(
            request_count_delta is not None
            and all(request_count_delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        if request_count_delta is None:
            errors.append("request_count_evidence_missing")
        elif not write_request_free:
            errors.append("unexpected_write_request_during_query")
        read_only_safe = auto_confirm is False and write_request_free
        if read_only and not read_only_safe:
            if auto_confirm is not False:
                errors.append("auto_settlement_confirm_not_disabled")

        account_rows = self._stable_ctp_query_rows(query_results["account"]["records"])
        position_rows = self._stable_ctp_query_rows(query_results["positions"]["records"])
        order_rows = self._stable_ctp_query_rows(query_results["orders"]["records"])
        trade_rows = self._stable_ctp_query_rows(query_results["trades"]["records"])
        instrument_rows = [
            self._normalise_ctp_instrument_row(row)
            for row in self._stable_ctp_query_rows(
                query_results.get("instruments", {}).get("records", ())
            )
        ]
        margin_rate_rows = self._stable_ctp_query_rows(
            query_results.get("margin_rate", {}).get("records", ())
        )
        commission_rate_rows = self._stable_ctp_query_rows(
            query_results.get("commission_rate", {}).get("records", ())
        )
        for row in order_rows:
            row.setdefault(
                "status",
                _normalize_ctp_order_status(
                    row.get("OrderStatus"), row.get("OrderSubmitStatus"), "submitted"
                ),
            )
            row.setdefault("order_ref", str(row.get("OrderRef") or "").strip())
            row.setdefault(
                "external_order_id",
                str(row.get("OrderSysID") or row.get("OrderRef") or "").strip(),
            )
            row.setdefault("remaining", _coerce_int(row.get("VolumeTotal"), 0))
        trading_day = trading_day_after or trading_day_before
        if not trading_day:
            for row in account_rows + position_rows + trade_rows:
                if row.get("TradingDay") not in (None, ""):
                    trading_day = str(row["TradingDay"])
                    break

        def _scope_trading_day(value: Any) -> str:
            return re.sub(r"[^0-9]", "", _coerce_text(value))

        trade_scope = {
            **trade_query_scope,
            "trading_day": _scope_trading_day(trading_day),
        }
        trade_result = query_results["trades"]
        trade_result["requested_scope"] = dict(trade_scope)
        trade_scope_errors = []
        for row in trade_rows:
            if exchange_id and _coerce_text(row.get("ExchangeID")).upper() != exchange_id:
                trade_scope_errors.append("trades_response_exchange_scope_mismatch")
            if (
                instrument_id
                and _normalize_ctp_instrument(row.get("InstrumentID"), exchange_id).upper()
                != instrument_id
            ):
                trade_scope_errors.append("trades_response_instrument_scope_mismatch")
            if (
                trade_scope["trading_day"]
                and _scope_trading_day(row.get("TradingDay")) != trade_scope["trading_day"]
            ):
                trade_scope_errors.append("trades_response_trading_day_scope_mismatch")
        if trade_scope_errors:
            # A native callback did arrive, but it does not prove the requested
            # read scope.  Mark the local acceptance result incomplete so all
            # callers retain the same fail-closed completion contract.
            trade_result.update(
                {
                    "complete": False,
                    "scope_valid": False,
                    "scope_validation_errors": sorted(set(trade_scope_errors)),
                    "error_code": "trade_scope_validation_failed",
                    "error_message": "trade_scope_validation_failed",
                }
            )
            errors.extend(trade_scope_errors)
        else:
            trade_result["scope_valid"] = True
        semantic = {
            "connection_generation": next(iter(generations), 0),
            "account_fingerprint": next(iter(fingerprints), ""),
            "trading_day": trading_day,
            "account": account_rows,
            "positions": position_rows,
            "orders": order_rows,
            "trades": trade_rows,
        }
        fingerprint = hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        active_orders = [row for row in order_rows if self._ctp_order_row_is_active(row)]
        nonzero_positions = [row for row in position_rows if self._ctp_position_row_is_nonzero(row)]
        required_query_names = ("account", "positions", "orders", "trades")
        request_ids = {name: all_request_ids[name] for name in required_query_names}
        composite_request_id = "|".join(
            f"{name}:{request_ids[name]}" for name in required_query_names
        )
        execution_summary = None
        summary_getter = getattr(self._api, "get_execution_summary", None)
        if callable(summary_getter):
            try:
                candidate_summary = summary_getter()
            except Exception:
                candidate_summary = None
            if isinstance(candidate_summary, Mapping):
                execution_summary = dict(candidate_summary)
        unknown_ids = (
            execution_summary.get("unknown_ids") if isinstance(execution_summary, Mapping) else None
        )
        unknown_intent_count = (
            len(unknown_ids) if isinstance(unknown_ids, (list, tuple, set)) else None
        )
        unmatched_trade_count = self._normalise_ctp_unmatched_trade_count(execution_summary)
        position_lots = 0.0
        for row in position_rows:
            raw_position = next(
                (
                    row.get(key)
                    for key in ("quantity", "size", "volume", "Position")
                    if row.get(key) not in (None, "")
                ),
                0.0,
            )
            try:
                position_lots += abs(float(raw_position))
            except (TypeError, ValueError):
                position_lots = None
                break
        complete = not errors
        timed_out = any(bool(query_results[name].get("timed_out")) for name in required_query_names)
        all_last_seen = all(
            query_results[name].get("is_last_seen") is True for name in required_query_names
        )
        first_error = next(
            (
                query_results[name].get("error_code")
                for name in query_results
                if query_results[name].get("error_code") not in (None, "", 0, "0")
            ),
            errors[0] if errors else None,
        )
        return {
            "schema_version": "backtrader.ctp.preflight.v1",
            "captured_at_utc": _dt.datetime.now(_UTC).isoformat(),
            "session": deepcopy(_redact_diagnostic(session)),
            "session_before": deepcopy(_redact_diagnostic(session_before)),
            "session_after": deepcopy(_redact_diagnostic(session_after)),
            "auto_settlement_confirm": auto_confirm,
            "read_only_safe": read_only_safe,
            "request_counts_before": request_counts_before,
            "request_counts_after": request_counts_after,
            "request_count_delta": request_count_delta,
            "write_request_free": write_request_free,
            "instrument_id": instrument_id or "",
            "exchange_id": exchange_id,
            # Echo the requested product scope so a Stage A product scan can
            # be distinguished from an exchange-wide scan by its consumers.
            "product_id": str(product_id or "").strip().upper(),
            "query_results": deepcopy(query_results),
            "account": account_rows,
            "positions": position_rows,
            "orders": order_rows,
            "trades": trade_rows,
            "instruments": instrument_rows,
            "margin_rate": margin_rate_rows,
            "commission_rate": commission_rate_rows,
            "active_orders": active_orders,
            "nonzero_positions": nonzero_positions,
            "connection_generation": semantic["connection_generation"],
            "account_fingerprint": semantic["account_fingerprint"],
            "reconciliation_fingerprint": fingerprint,
            "snapshot_hash": fingerprint,
            "request_ids": request_ids,
            "all_request_ids": all_request_ids,
            "request_id": composite_request_id,
            "trading_day": trading_day,
            "complete": complete,
            "is_last_seen": all_last_seen,
            "timed_out": timed_out,
            "error_code": first_error,
            "completed_monotonic": time.monotonic(),
            "started_monotonic": query_started_monotonic,
            "position_lots": position_lots,
            "active_order_count": len(active_orders),
            "unknown_intent_count": unknown_intent_count,
            "unmatched_trade_count": unmatched_trade_count,
            "execution_summary": deepcopy(_redact_diagnostic(execution_summary)),
            "evidence_complete": complete,
            "evidence_errors": sorted(set(errors)),
            "flat": not active_orders and not nonzero_positions,
        }

    @staticmethod
    def _ctp_preflight_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
        """Hash the complete stable evidence returned by one preflight query group."""
        fields = (
            "schema_version",
            "session_before",
            "session_after",
            "auto_settlement_confirm",
            "read_only_safe",
            "request_counts_before",
            "request_counts_after",
            "request_count_delta",
            "write_request_free",
            "instrument_id",
            "exchange_id",
            "query_results",
            "account",
            "positions",
            "orders",
            "trades",
            "instruments",
            "margin_rate",
            "commission_rate",
            "connection_generation",
            "account_fingerprint",
            "request_ids",
            "all_request_ids",
            "trading_day",
            "complete",
            "is_last_seen",
            "timed_out",
            "error_code",
            "evidence_complete",
            "evidence_errors",
            "flat",
        )
        material = {field: snapshot.get(field) for field in fields}
        return hashlib.sha256(
            json.dumps(
                material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def get_ctp_preflight_snapshot(
        self,
        instrument_id: Optional[str] = None,
        *,
        exchange_id: str = "",
        product_id: str = "",
        timeout: float = 15.0,
        read_only: bool = True,
    ) -> Dict[str, Any]:
        """Query one fail-closed CTP startup snapshot through the bound client."""
        exchange_id = _coerce_text(exchange_id).upper()
        if instrument_id:
            parsed_instrument, parsed_exchange = _split_ctp_symbol(instrument_id)
            instrument_id = parsed_instrument or str(instrument_id)
            exchange_id = exchange_id or parsed_exchange
            canonical_scope = _canonical_ctp_scope(instrument_id, exchange_id)
            if canonical_scope:
                exchange_id, instrument_id = canonical_scope.split(".", 1)
        product_id = str(product_id or "").strip().upper()
        snapshot = self._build_ctp_query_snapshot(
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            product_id=product_id,
            timeout=max(float(timeout), 0.0),
            include_reference_data=True,
            read_only=read_only,
        )
        snapshot["snapshot_sha256"] = self._ctp_preflight_snapshot_sha256(snapshot)
        self._last_ctp_preflight_snapshot = deepcopy(snapshot)
        self._ctp_preflight_history.append(deepcopy(snapshot))
        return snapshot

    def get_ctp_bundle_preflight_snapshot(
        self,
        legs: Any,
        *,
        primary_leg: Any = None,
        primary_instrument_id: Any = None,
        timeout: float = 15.0,
        read_only: bool = True,
    ) -> Dict[str, Any]:
        """Return one fail-closed, read-only CTP futures/options bundle snapshot.

        ``legs`` contains two or three *raw* ``(exchange_id, instrument_id)``
        identities.  A mapping may instead carry the same fields and an
        ``is_primary`` boolean.  The raw values are deliberately never passed
        through the V1 friendly-symbol canonicaliser: DCE option IDs are native
        wire identifiers and must remain byte-for-byte distinguishable in the
        resulting evidence.

        This snapshot is an observation primitive only.  It is not cached as a
        V1 authorization preflight and it neither confirms settlement nor arms
        or submits CTP execution.
        """
        if read_only is not True:
            raise BtApiStoreError("CTP bundle preflight is read-only")
        parsed_legs = self._normalise_ctp_bundle_legs(
            legs,
            primary_leg=primary_leg,
            primary_instrument_id=primary_instrument_id,
        )
        if not self._is_ctp_session_provider():
            raise BtApiStoreError("CTP bundle preflight requires a CTP provider")
        try:
            total_timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("CTP bundle query timeout must be finite and nonnegative") from exc
        if not math.isfinite(total_timeout) or total_timeout < 0:
            raise ValueError("CTP bundle query timeout must be finite and nonnegative")

        query_started_monotonic = time.monotonic()
        deadline = query_started_monotonic + total_timeout if total_timeout > 0 else None
        # Capture the write counters before lazy connection.  Calling
        # ``_ensure_api_ready`` may invoke a provider's connect/start path, so
        # a post-connect baseline alone cannot prove this preflight was read
        # only.
        session_before_connect = self._read_ctp_session_state()
        request_counts_before_connect = self._ctp_request_counts(session_before_connect)
        self._ensure_api_ready()
        session_before = self._read_ctp_session_state()
        request_counts_before_query = self._ctp_request_counts(session_before)
        connect_request_count_delta = self._ctp_request_count_delta(
            request_counts_before_connect, request_counts_before_query
        )
        targets = self._ctp_query_targets()
        target = targets[0] if targets else None
        query_results: Dict[str, Dict[str, Any]] = {}
        query_sent_at_utc: Dict[str, _dt.datetime] = {}
        leg_query_keys: Dict[int, Dict[str, str]] = {index: {} for index in range(len(parsed_legs))}

        def _run_query(
            label: str,
            request_type: str,
            method_name: str,
            kwargs: Mapping[str, Any],
        ) -> None:
            # These boundaries belong to the Store.  A provider may return
            # fields with the same names, but it cannot replace the local
            # observations used to prove that this result belongs to this
            # request.
            sent_at_utc = _dt.datetime.now(_UTC)
            try:
                sent_monotonic = float(time.monotonic())
            except (TypeError, ValueError, OverflowError):
                sent_monotonic = math.nan
            if target is None:
                result = self._ctp_query_failure(
                    request_type, session_before, "query_capability_unavailable"
                )
            else:
                request_timeout = (
                    self._reserve_ctp_query_slot(deadline) if deadline is not None else 0.0
                )
                if request_timeout is None:
                    result = self._ctp_query_failure(
                        request_type, session_before, "query_deadline_exceeded"
                    )
                else:
                    # Exclude any rate-limit sleep from the Store's request
                    # envelope: the lower bound is the instant immediately
                    # before the provider call.
                    sent_at_utc = _dt.datetime.now(_UTC)
                    try:
                        sent_monotonic = float(time.monotonic())
                    except (TypeError, ValueError, OverflowError):
                        sent_monotonic = math.nan
                    try:
                        result = self._normalise_ctp_query_result(
                            self._invoke_ctp_query(
                                target,
                                request_type,
                                method_name,
                                timeout=request_timeout,
                                kwargs=kwargs,
                            ),
                            request_type,
                        )
                    except Exception as exc:
                        result = self._ctp_query_failure(
                            request_type, session_before, type(exc).__name__
                        )
            received_at_utc = _dt.datetime.now(_UTC)
            try:
                received_monotonic = float(time.monotonic())
            except (TypeError, ValueError, OverflowError):
                received_monotonic = math.nan
            query_sent_at_utc[label] = sent_at_utc
            result["requested_at_utc"] = sent_at_utc.isoformat()
            result["received_at_utc"] = received_at_utc.isoformat()
            result["requested_monotonic"] = sent_monotonic
            result["received_monotonic"] = received_monotonic
            query_results[label] = result

        # Account-level safety evidence is intentionally unfiltered.  A bundle
        # must not hide an unrelated open order, position, or trade by applying
        # an instrument filter to these terminal queries.
        with self._ctp_query_lock:
            for request_type, method_name in (
                ("account", "query_account_result"),
                ("positions", "query_positions_result"),
                ("orders", "query_orders_result"),
                ("trades", "query_trades_result"),
            ):
                _run_query(request_type, request_type, method_name, {})

            # First obtain each instrument response so that option-only
            # reference queries are driven by returned CTP metadata, never a
            # brittle parser for native instrument names.
            provisional_metadata: Dict[int, Optional[Dict[str, Any]]] = {}
            for index, leg in enumerate(parsed_legs):
                label = f"leg[{index}].instrument"
                leg_query_keys[index]["instrument"] = label
                _run_query(
                    label,
                    "instruments",
                    "query_instruments_result",
                    {
                        "instrument_id": leg["instrument_id"],
                        "exchange_id": leg["exchange_id"],
                    },
                )
                instrument_rows = self._stable_ctp_query_rows(query_results[label].get("records"))
                instrument, _unused_errors = self._ctp_bundle_reference_match(
                    instrument_rows,
                    exchange_id=leg["exchange_id"],
                    instrument_id=leg["instrument_id"],
                    label=label,
                    require_exchange=True,
                )
                provisional_metadata[index] = (
                    self._ctp_bundle_instrument_metadata(instrument)
                    if instrument is not None
                    else None
                )

            for index, leg in enumerate(parsed_legs):
                # Generic margin/commission reference rows are required for
                # futures only.  Options have a separate native cost model;
                # an empty generic response is normal and must not be treated
                # as evidence failure.
                metadata = provisional_metadata[index]
                if not metadata or metadata.get("asset_type") != "future":
                    continue
                for field, request_type, method_name in (
                    ("margin_rate", "margin_rate", "query_instrument_margin_rate_result"),
                    (
                        "commission_rate",
                        "commission_rate",
                        "query_instrument_commission_rate_result",
                    ),
                ):
                    label = f"leg[{index}].{field}"
                    leg_query_keys[index][field] = label
                    _run_query(
                        label,
                        request_type,
                        method_name,
                        {
                            "instrument_id": leg["instrument_id"],
                            "exchange_id": leg["exchange_id"],
                        },
                    )

            for index, leg in enumerate(parsed_legs):
                metadata = provisional_metadata[index]
                if not metadata or metadata.get("asset_type") != "option":
                    continue
                for field, request_type, method_name, kwargs in (
                    (
                        "option_trade_cost",
                        "option_trade_cost",
                        "query_option_instrument_trade_cost_result",
                        {
                            "instrument_id": leg["instrument_id"],
                            "exchange_id": leg["exchange_id"],
                            "hedge_flag": "1",
                            # A zero native input is explicitly a reference
                            # query; it does not imply a current executable
                            # mark or a portfolio margin estimate.
                            "input_price": 0.0,
                            "underlying_price": 0.0,
                        },
                    ),
                    (
                        "option_commission_rate",
                        "option_commission_rate",
                        "query_option_instrument_commission_rate_result",
                        {
                            "instrument_id": leg["instrument_id"],
                            "exchange_id": leg["exchange_id"],
                        },
                    ),
                ):
                    label = f"leg[{index}].{field}"
                    leg_query_keys[index][field] = label
                    _run_query(label, request_type, method_name, kwargs)

        session_after = self._read_ctp_session_state()
        request_counts_after = self._ctp_request_counts(session_after)
        query_request_count_delta = self._ctp_request_count_delta(
            request_counts_before_query, request_counts_after
        )
        request_count_delta = self._ctp_request_count_delta(
            request_counts_before_connect, request_counts_after
        )
        session = session_after if session_after else session_before
        errors: List[str] = []
        for label, result in query_results.items():
            if not self._ctp_query_result_complete(result):
                errors.append(f"{label}_query_incomplete")
            if result.get("request_type_matches") is not True:
                errors.append(f"{label}_request_type_mismatch")
            if result.get("records_schema_valid") is not True:
                errors.append(f"{label}_records_schema_invalid")
            errors.extend(
                self._ctp_bundle_query_time_errors(
                    result,
                    label=label,
                    requested_at_utc=query_sent_at_utc[label],
                    received_at_utc=result.get("received_at_utc"),
                )
            )

        def _session_generation(value: Mapping[str, Any]) -> int:
            raw = value.get("connection_generation")
            if isinstance(raw, bool):
                return 0
            try:
                parsed = int(raw or 0)
            except (TypeError, ValueError):
                return 0
            return parsed if parsed > 0 else 0

        generation_before = _session_generation(session_before)
        generation_after = _session_generation(session_after)
        fingerprint_before = str(session_before.get("account_fingerprint") or "").strip()
        fingerprint_after = str(session_after.get("account_fingerprint") or "").strip()
        trading_day_before = self._ctp_bundle_valid_trading_day(session_before.get("trading_day"))
        trading_day_after = self._ctp_bundle_valid_trading_day(session_after.get("trading_day"))
        if generation_before <= 0 or generation_after <= 0:
            errors.append("session_generation_missing")
        elif generation_before != generation_after:
            errors.append("session_generation_changed")
        if not fingerprint_before or not fingerprint_after:
            errors.append("session_account_fingerprint_missing")
        elif fingerprint_before != fingerprint_after:
            errors.append("session_account_fingerprint_changed")
        if not trading_day_before or not trading_day_after:
            errors.append("session_trading_day_missing")
        elif trading_day_before != trading_day_after:
            errors.append("session_trading_day_changed")
        trading_day = trading_day_after or trading_day_before

        complete_results = [
            result for result in query_results.values() if self._ctp_query_result_complete(result)
        ]
        query_generations = {int(result["connection_generation"]) for result in complete_results}
        query_fingerprints = {str(result["account_fingerprint"]) for result in complete_results}
        if len(query_generations) != 1:
            errors.append("query_generation_mismatch")
        if len(query_fingerprints) != 1:
            errors.append("query_account_fingerprint_mismatch")
        if generation_after > 0 and query_generations != {generation_after}:
            errors.append("query_generation_session_mismatch")
        if fingerprint_after and query_fingerprints != {fingerprint_after}:
            errors.append("query_account_fingerprint_session_mismatch")

        all_request_ids: Dict[str, int] = {}
        for label, result in query_results.items():
            raw_request_id = result.get("request_id")
            if isinstance(raw_request_id, bool):
                request_id = 0
            else:
                try:
                    request_id = int(raw_request_id or 0)
                except (TypeError, ValueError):
                    request_id = 0
            all_request_ids[label] = request_id
        positive_request_ids = [value for value in all_request_ids.values() if value > 0]
        if len(set(positive_request_ids)) != len(positive_request_ids):
            errors.append("query_request_id_not_unique")

        auto_confirm = session.get(
            "auto_settlement_confirm",
            getattr(target, "auto_settlement_confirm", None) if target is not None else None,
        )
        # Include the lazy connection interval in the read-only guarantee.
        # Capturing only a post-connect baseline would make a write performed
        # by a provider's connect/start path invisible to this evidence.
        connect_write_request_free = bool(
            connect_request_count_delta is not None
            and all(connect_request_count_delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        query_write_request_free = bool(
            query_request_count_delta is not None
            and all(query_request_count_delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        total_write_request_free = bool(
            request_count_delta is not None
            and all(request_count_delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        write_request_free = bool(
            connect_write_request_free and query_write_request_free and total_write_request_free
        )
        if request_counts_before_connect is None:
            errors.append("preconnect_request_count_evidence_missing")
        if request_counts_before_query is None:
            errors.append("postconnect_request_count_evidence_missing")
        if request_counts_after is None:
            errors.append("request_count_evidence_missing")
        if connect_request_count_delta is None:
            errors.append("connect_request_count_evidence_missing")
        elif not connect_write_request_free:
            errors.append("unexpected_write_request_during_connect")
        if query_request_count_delta is None:
            errors.append("query_request_count_evidence_missing")
        elif not query_write_request_free:
            errors.append("unexpected_write_request_during_query")
        if request_count_delta is None:
            errors.append("preflight_request_count_evidence_missing")
        elif not total_write_request_free:
            errors.append("unexpected_write_request_during_preflight")
        if auto_confirm is not False:
            errors.append("auto_settlement_confirm_not_disabled")
        session_ready = bool(session.get("read_only_ready") is True or session.get("ready") is True)
        if not session_ready:
            errors.append("ctp_session_not_ready")

        account_rows = self._stable_ctp_query_rows(query_results["account"].get("records"))
        position_rows = self._stable_ctp_query_rows(query_results["positions"].get("records"))
        order_rows = self._stable_ctp_query_rows(query_results["orders"].get("records"))
        trade_rows = self._stable_ctp_query_rows(query_results["trades"].get("records"))
        errors.extend(self._ctp_bundle_account_evidence_errors(account_rows))
        for label, result in query_results.items():
            errors.extend(
                self._ctp_bundle_row_trading_day_errors(
                    self._stable_ctp_query_rows(result.get("records")),
                    label=label,
                    trading_day=trading_day,
                )
            )

        leg_evidence: List[Dict[str, Any]] = []
        for index, leg in enumerate(parsed_legs):
            local_errors: List[str] = []
            query_keys = leg_query_keys[index]
            references: Dict[str, Optional[Dict[str, Any]]] = {}
            for field, require_exchange in (
                ("instrument", True),
                ("margin_rate", False),
                ("commission_rate", False),
                ("option_trade_cost", False),
                ("option_commission_rate", False),
            ):
                label = query_keys.get(field)
                if label is None:
                    continue
                record, record_errors = self._ctp_bundle_reference_match(
                    self._stable_ctp_query_rows(query_results[label].get("records")),
                    exchange_id=leg["exchange_id"],
                    instrument_id=leg["instrument_id"],
                    label=label,
                    require_exchange=require_exchange,
                )
                references[field] = record
                local_errors.extend(record_errors)
            instrument = references.get("instrument")
            metadata = (
                self._ctp_bundle_instrument_metadata(instrument) if instrument is not None else None
            )
            if metadata is None:
                local_errors.append(f"leg[{index}].instrument_metadata_missing")
            else:
                local_errors.extend(
                    self._ctp_bundle_instrument_evidence_errors(
                        instrument, label=f"leg[{index}].instrument"
                    )
                )
                margin_rate = references.get("margin_rate")
                if margin_rate is not None:
                    local_errors.extend(
                        self._ctp_bundle_margin_evidence_errors(
                            margin_rate, label=f"leg[{index}].margin_rate"
                        )
                    )
                commission_rate = references.get("commission_rate")
                if commission_rate is not None:
                    local_errors.extend(
                        self._ctp_bundle_commission_evidence_errors(
                            commission_rate, label=f"leg[{index}].commission_rate"
                        )
                    )
                if metadata["is_trading"] is not True:
                    local_errors.append(f"leg[{index}].instrument_not_trading")
                if not self._ctp_bundle_valid_trading_day(metadata["expiry_date"]):
                    local_errors.append(f"leg[{index}].expiry_unavailable")
                asset_type_alias_error = metadata["asset_type_alias_error"]
                if asset_type_alias_error in {"invalid", "mismatch"}:
                    local_errors.append(
                        f"leg[{index}].instrument_asset_type_alias_{asset_type_alias_error}"
                    )
                if metadata["asset_type"] == "option":
                    if not metadata["underlying_instrument_id"]:
                        local_errors.append(f"leg[{index}].option_underlying_missing")
                    if not metadata["underlying_aliases_consistent"]:
                        local_errors.append(f"leg[{index}].option_underlying_alias_mismatch")
                    option_type_alias_error = metadata["option_type_alias_error"]
                    if option_type_alias_error in {"invalid", "mismatch"}:
                        local_errors.append(
                            f"leg[{index}].option_type_alias_{option_type_alias_error}"
                        )
                    if metadata["option_type"] not in {"call", "put"}:
                        local_errors.append(f"leg[{index}].option_call_put_unavailable")
                    strike_price = metadata["strike_price"]
                    if metadata["strike_numeric_error"] == "alias_mismatch":
                        local_errors.append(f"leg[{index}].option_strike_alias_mismatch")
                    elif strike_price is None or strike_price <= 0:
                        local_errors.append(f"leg[{index}].option_strike_unavailable")
                    for field in ("option_trade_cost", "option_commission_rate"):
                        if field not in references:
                            local_errors.append(f"leg[{index}].{field}_query_missing")
                    option_trade_cost = references.get("option_trade_cost")
                    if option_trade_cost is not None:
                        local_errors.extend(
                            self._ctp_bundle_option_trade_cost_evidence_errors(
                                option_trade_cost,
                                label=f"leg[{index}].option_trade_cost",
                            )
                        )
                    option_commission_rate = references.get("option_commission_rate")
                    if option_commission_rate is not None:
                        local_errors.extend(
                            self._ctp_bundle_commission_evidence_errors(
                                option_commission_rate,
                                label=f"leg[{index}].option_commission_rate",
                            )
                        )
            query_evidence = {
                field: deepcopy(query_results[label]) for field, label in query_keys.items()
            }
            local_errors = sorted(set(local_errors))
            errors.extend(local_errors)
            leg_evidence.append(
                {
                    **leg,
                    "instrument": deepcopy(instrument),
                    "margin_rate": deepcopy(references.get("margin_rate")),
                    "commission_rate": deepcopy(references.get("commission_rate")),
                    "option_trade_cost": deepcopy(references.get("option_trade_cost")),
                    "option_commission_rate": deepcopy(references.get("option_commission_rate")),
                    "metadata": deepcopy(metadata),
                    "query_results": query_evidence,
                    "evidence_complete": not local_errors,
                    "evidence_errors": local_errors,
                }
            )

        futures = [
            item
            for item in leg_evidence
            if isinstance(item.get("metadata"), Mapping)
            and item["metadata"].get("asset_type") == "future"
        ]
        options = [
            item
            for item in leg_evidence
            if isinstance(item.get("metadata"), Mapping)
            and item["metadata"].get("asset_type") == "option"
        ]
        primary = next(item for item in leg_evidence if item["is_primary"])
        if len(futures) != 1:
            errors.append("bundle_requires_exactly_one_future")
        if primary not in futures:
            errors.append("bundle_primary_leg_must_be_future")
        expected_option_count = len(parsed_legs) - 1
        if len(options) != expected_option_count:
            errors.append("bundle_option_leg_count_invalid")
        future = futures[0] if len(futures) == 1 else None
        if future is not None:
            future_metadata = future["metadata"]
            if not self._ctp_bundle_valid_trading_day(future_metadata.get("expiry_date")):
                errors.append("bundle_future_expiry_unavailable")
            for option in options:
                option_metadata = option["metadata"]
                if option_metadata["underlying_instrument_id"] != future["instrument_id"]:
                    errors.append("bundle_option_underlying_mismatch")
        if len(parsed_legs) == 3:
            option_types = {item["metadata"].get("option_type") for item in options}
            if option_types != {"call", "put"}:
                errors.append("bundle_call_put_pair_invalid")
            if len(options) == 2:
                first_expiry = options[0]["metadata"].get("expiry_date")
                second_expiry = options[1]["metadata"].get("expiry_date")
                if first_expiry != second_expiry:
                    errors.append("bundle_call_put_expiry_mismatch")
                first_strike = options[0]["metadata"].get("strike_price")
                second_strike = options[1]["metadata"].get("strike_price")
                if (
                    first_strike is None
                    or second_strike is None
                    or not math.isclose(first_strike, second_strike, rel_tol=0.0, abs_tol=1e-12)
                ):
                    errors.append("bundle_call_put_strike_mismatch")

        active_orders = [row for row in order_rows if self._ctp_order_row_is_active(row)]
        nonzero_positions = [row for row in position_rows if self._ctp_position_row_is_nonzero(row)]
        required_account_labels = ("account", "positions", "orders", "trades")
        request_ids = {label: all_request_ids[label] for label in required_account_labels}
        execution_summary = None
        summary_getter = getattr(self._api, "get_execution_summary", None)
        if callable(summary_getter):
            try:
                candidate_summary = summary_getter()
            except Exception:
                candidate_summary = None
            if isinstance(candidate_summary, Mapping):
                execution_summary = dict(candidate_summary)
        unknown_ids = (
            execution_summary.get("unknown_ids") if isinstance(execution_summary, Mapping) else None
        )
        unknown_intent_count = (
            len(unknown_ids) if isinstance(unknown_ids, (list, tuple, set)) else None
        )
        unmatched_trade_count = self._normalise_ctp_unmatched_trade_count(execution_summary)
        position_lots: Optional[float] = 0.0
        for row in position_rows:
            raw_position = next(
                (
                    row.get(key)
                    for key in ("quantity", "size", "volume", "Position")
                    if row.get(key) not in (None, "")
                ),
                0.0,
            )
            try:
                position_lots += abs(float(raw_position))
            except (TypeError, ValueError):
                position_lots = None
                break
        try:
            query_completed_monotonic = float(time.monotonic())
        except (TypeError, ValueError, OverflowError):
            query_completed_monotonic = math.nan
        try:
            query_started_value = float(query_started_monotonic)
        except (TypeError, ValueError, OverflowError):
            query_started_value = math.nan
        if not math.isfinite(query_started_value) or query_started_value < 0:
            errors.append("bundle_query_started_monotonic_invalid")
        if not math.isfinite(query_completed_monotonic) or query_completed_monotonic < 0:
            errors.append("bundle_query_completed_monotonic_invalid")
        elif math.isfinite(query_started_value) and query_completed_monotonic < query_started_value:
            errors.append("bundle_query_completed_monotonic_before_started")
        evidence_errors = sorted(set(errors))
        all_last_seen = all(result.get("is_last_seen") is True for result in query_results.values())
        timed_out = any(bool(result.get("timed_out")) for result in query_results.values())
        first_error = next(
            (
                result.get("error_code")
                for result in query_results.values()
                if result.get("error_code") not in (None, "", 0, "0")
            ),
            evidence_errors[0] if evidence_errors else None,
        )
        snapshot = {
            "schema_version": "backtrader.ctp.bundle-preflight.v2",
            "captured_at_utc": _dt.datetime.now(_UTC).isoformat(),
            "read_only": True,
            "execution_eligible": False,
            "exchange_id": parsed_legs[0]["exchange_id"],
            "primary_leg": {
                "exchange_id": primary["exchange_id"],
                "instrument_id": primary["instrument_id"],
            },
            "legs": leg_evidence,
            "session": deepcopy(_redact_diagnostic(session)),
            "session_before_connect": deepcopy(_redact_diagnostic(session_before_connect)),
            "session_before": deepcopy(_redact_diagnostic(session_before)),
            "session_after": deepcopy(_redact_diagnostic(session_after)),
            "auto_settlement_confirm": auto_confirm,
            "read_only_safe": auto_confirm is False and write_request_free,
            "request_counts_before_connect": request_counts_before_connect,
            "request_counts_after_connect": request_counts_before_query,
            "connect_request_count_delta": connect_request_count_delta,
            "request_counts_before_query": request_counts_before_query,
            "request_counts_before": request_counts_before_connect,
            "request_counts_after": request_counts_after,
            "query_request_count_delta": query_request_count_delta,
            "request_count_delta": request_count_delta,
            "connect_write_request_free": connect_write_request_free,
            "query_write_request_free": query_write_request_free,
            "write_request_free": write_request_free,
            "query_results": deepcopy(query_results),
            "account": account_rows,
            "positions": position_rows,
            "orders": order_rows,
            "trades": trade_rows,
            "active_orders": active_orders,
            "nonzero_positions": nonzero_positions,
            "connection_generation": next(iter(query_generations), 0),
            "account_fingerprint": next(iter(query_fingerprints), ""),
            "trading_day": trading_day,
            "request_ids": request_ids,
            "all_request_ids": all_request_ids,
            "complete": not evidence_errors,
            "evidence_complete": not evidence_errors,
            "evidence_errors": evidence_errors,
            "is_last_seen": all_last_seen,
            "timed_out": timed_out,
            "error_code": first_error,
            "started_monotonic": query_started_monotonic,
            "completed_monotonic": query_completed_monotonic,
            "position_lots": position_lots,
            "active_order_count": len(active_orders),
            "unknown_intent_count": unknown_intent_count,
            "unmatched_trade_count": unmatched_trade_count,
            "execution_summary": deepcopy(_redact_diagnostic(execution_summary)),
            "flat": not active_orders and not nonzero_positions,
        }
        snapshot["snapshot_sha256"] = self._ctp_bundle_snapshot_sha256(snapshot)
        # Keep the latest bundle evidence separate from the V1 single-leg
        # history.  Arming must consume this exact scope and must re-fence it
        # against the current account/day/generation before any SDK write.
        self._last_ctp_bundle_preflight_snapshot = deepcopy(snapshot)
        return snapshot

    def get_ctp_bundle_quote_reference_snapshot(
        self,
        legs: Any,
        *,
        primary_leg: Any = None,
        primary_instrument_id: Any = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Refresh only depth quotes against one already-frozen bundle preflight.

        This is deliberately not a shortcut to ``get_ctp_bundle_preflight_snapshot``.
        It cannot establish a new account/position/order/trade observation and
        consequently remains fail-closed until a complete, read-only bundle
        preflight already exists on this exact Store instance.
        """
        raw_legs = list(legs) if not isinstance(legs, (list, tuple)) else list(legs)
        parsed_legs = self._normalise_ctp_bundle_legs(
            raw_legs,
            primary_leg=primary_leg,
            primary_instrument_id=primary_instrument_id,
        )
        if len(parsed_legs) != 3:
            return self._finish_ctp_bundle_quote_reference_snapshot(
                {}, {}, ["bundle_quote_reference_requires_exactly_three_legs"], parsed_legs
            )
        try:
            total_timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("CTP bundle quote timeout must be finite and nonnegative") from exc
        if not math.isfinite(total_timeout) or total_timeout < 0:
            raise ValueError("CTP bundle quote timeout must be finite and nonnegative")

        frozen = self._last_ctp_bundle_preflight_snapshot
        if frozen is None:
            return self._finish_ctp_bundle_quote_reference_snapshot(
                {}, {}, ["bundle_quote_preflight_snapshot_missing"], parsed_legs
            )
        preflight = deepcopy(frozen)
        try:
            scope = self._ctp_bundle_snapshot_scope(preflight)
        except BtApiStoreError:
            return self._finish_ctp_bundle_quote_reference_snapshot(
                preflight, {}, ["bundle_quote_preflight_snapshot_invalid"], parsed_legs
            )

        errors: List[str] = []
        requested_scope = sorted(
            f"{leg['exchange_id']}.{leg['instrument_id']}" for leg in parsed_legs
        )
        requested_primary = next(
            f"{leg['exchange_id']}.{leg['instrument_id']}"
            for leg in parsed_legs
            if leg["is_primary"] is True
        )
        if requested_scope != list(scope.get("authorized_instruments") or ()):
            errors.append("bundle_quote_requested_legs_mismatch")
        if requested_primary != scope.get("instrument"):
            errors.append("bundle_quote_requested_primary_mismatch")

        expected_account = self._normalized_account_fingerprint(scope.get("account_fingerprint"))
        expected_day = self._ctp_bundle_valid_trading_day(scope.get("trading_day"))
        try:
            expected_generation = int(scope.get("connection_generation") or 0)
        except (TypeError, ValueError):
            expected_generation = 0
        if not expected_account:
            errors.append("bundle_quote_preflight_account_fingerprint_invalid")
        if not expected_day:
            errors.append("bundle_quote_preflight_trading_day_invalid")
        if expected_generation <= 0:
            errors.append("bundle_quote_preflight_generation_invalid")
        if not self._is_ctp_session_provider():
            errors.append("bundle_quote_ctp_provider_unavailable")

        session_before = self._read_ctp_session_state()
        before_counts = self._ctp_request_counts(session_before)
        try:
            current_generation = int(session_before.get("connection_generation") or 0)
        except (TypeError, ValueError):
            current_generation = 0
        current_account = self._normalized_account_fingerprint(
            session_before.get("account_fingerprint")
        )
        current_day = self._ctp_bundle_valid_trading_day(session_before.get("trading_day"))
        if current_generation != expected_generation:
            errors.append("bundle_quote_current_generation_mismatch")
        if current_account != expected_account:
            errors.append("bundle_quote_current_account_fingerprint_mismatch")
        if current_day != expected_day:
            errors.append("bundle_quote_current_trading_day_mismatch")
        if (
            session_before.get("read_only_ready") is not True
            and session_before.get("ready") is not True
        ):
            errors.append("bundle_quote_current_session_not_ready")
        if errors:
            return self._finish_ctp_bundle_quote_reference_snapshot(
                preflight,
                {},
                errors,
                parsed_legs,
                scope=scope,
                current_session=session_before,
            )

        deadline = time.monotonic() + total_timeout if total_timeout > 0 else None
        targets = self._ctp_query_targets()
        target = targets[0] if targets else None
        results: Dict[str, Dict[str, Any]] = {}
        request_windows: Dict[str, Tuple[_dt.datetime, _dt.datetime]] = {}

        def run_depth(index: int, leg: Mapping[str, Any]) -> None:
            label = f"leg[{index}].depth_market_data"
            sent_at = _dt.datetime.now(_UTC)
            try:
                sent_monotonic = float(time.monotonic())
            except (TypeError, ValueError, OverflowError):
                sent_monotonic = math.nan
            if target is None:
                result = self._ctp_query_failure(
                    "depth_market_data", session_before, "query_capability_unavailable"
                )
            else:
                request_timeout = (
                    self._reserve_ctp_query_slot(deadline) if deadline is not None else 0.0
                )
                if request_timeout is None:
                    result = self._ctp_query_failure(
                        "depth_market_data", session_before, "query_deadline_exceeded"
                    )
                else:
                    sent_at = _dt.datetime.now(_UTC)
                    try:
                        sent_monotonic = float(time.monotonic())
                    except (TypeError, ValueError, OverflowError):
                        sent_monotonic = math.nan
                    try:
                        result = self._normalise_ctp_query_result(
                            self._invoke_ctp_query(
                                target,
                                "depth_market_data",
                                "query_depth_market_data_result",
                                timeout=request_timeout,
                                kwargs={
                                    "instrument_id": leg["instrument_id"],
                                    "exchange_id": leg["exchange_id"],
                                },
                            ),
                            "depth_market_data",
                        )
                    except Exception as exc:
                        result = self._ctp_query_failure(
                            "depth_market_data", session_before, type(exc).__name__
                        )
            received_at = _dt.datetime.now(_UTC)
            try:
                received_monotonic = float(time.monotonic())
            except (TypeError, ValueError, OverflowError):
                received_monotonic = math.nan
            result["requested_at_utc"] = sent_at.isoformat()
            result["received_at_utc"] = received_at.isoformat()
            result["requested_monotonic"] = sent_monotonic
            result["received_monotonic"] = received_monotonic
            results[label] = result
            request_windows[label] = (sent_at, received_at)

        with self._ctp_query_lock:
            for index, leg in enumerate(parsed_legs):
                run_depth(index, leg)

        quote_evidence: Dict[int, Dict[str, Any]] = {}
        for index, leg in enumerate(parsed_legs):
            label = f"leg[{index}].depth_market_data"
            result = results[label]
            if not self._ctp_query_result_complete(result):
                errors.append(f"{label}_query_incomplete")
            if result.get("schema_version") in (None, ""):
                errors.append(f"{label}_schema_version_missing")
            if (
                self._normalized_account_fingerprint(result.get("account_fingerprint"))
                != expected_account
            ):
                errors.append(f"{label}_account_fingerprint_mismatch")
            try:
                result_generation = int(result.get("connection_generation") or 0)
            except (TypeError, ValueError):
                result_generation = 0
            if result_generation != expected_generation:
                errors.append(f"{label}_connection_generation_mismatch")
            if self._ctp_bundle_valid_trading_day(result.get("trading_day")) != expected_day:
                errors.append(f"{label}_trading_day_mismatch")
            errors.extend(
                self._ctp_bundle_query_time_errors(
                    result,
                    label=label,
                    requested_at_utc=request_windows[label][0],
                    received_at_utc=request_windows[label][1],
                )
            )
            record, record_errors = self._ctp_execution_reference_record(
                result.get("records"), leg, label=label
            )
            errors.extend(record_errors)
            quote, quote_errors = self._ctp_execution_reference_quote(record, label=label)
            errors.extend(quote_errors)
            quote_evidence[index] = {
                "instrument_id": leg["instrument_id"],
                "exchange_id": leg["exchange_id"],
                "bid_price": quote.get("bid_price") if quote is not None else None,
                "ask_price": quote.get("ask_price") if quote is not None else None,
                "bid_volume": quote.get("bid_volume") if quote is not None else None,
                "ask_volume": quote.get("ask_volume") if quote is not None else None,
                "entry_buy_price": quote.get("ask_price") if quote is not None else None,
                "exit_sell_price": quote.get("bid_price") if quote is not None else None,
                "requested_at_utc": result.get("requested_at_utc"),
                "received_at_utc": result.get("received_at_utc"),
                "requested_monotonic": result.get("requested_monotonic"),
                "received_monotonic": result.get("received_monotonic"),
                "request_id": result.get("request_id"),
            }

        request_ids: Dict[str, int] = {}
        for label, result in results.items():
            try:
                request_id = int(result.get("request_id") or 0)
            except (TypeError, ValueError):
                request_id = 0
            request_ids[label] = request_id
        if any(value <= 0 for value in request_ids.values()):
            errors.append("bundle_quote_request_id_missing")
        elif len(set(request_ids.values())) != len(request_ids):
            errors.append("bundle_quote_request_id_not_unique")

        session_after = self._read_ctp_session_state()
        after_counts = self._ctp_request_counts(session_after)
        request_count_delta = self._ctp_request_count_delta(before_counts, after_counts)
        write_request_free = bool(
            request_count_delta is not None
            and all(request_count_delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        if not write_request_free:
            errors.append("bundle_quote_write_request_evidence_invalid")
        try:
            after_generation = int(session_after.get("connection_generation") or 0)
        except (TypeError, ValueError):
            after_generation = 0
        if after_generation != expected_generation:
            errors.append("bundle_quote_session_generation_changed")
        if (
            self._normalized_account_fingerprint(session_after.get("account_fingerprint"))
            != expected_account
        ):
            errors.append("bundle_quote_session_account_fingerprint_changed")
        if self._ctp_bundle_valid_trading_day(session_after.get("trading_day")) != expected_day:
            errors.append("bundle_quote_session_trading_day_changed")
        if (
            session_after.get("read_only_ready") is not True
            and session_after.get("ready") is not True
        ):
            errors.append("bundle_quote_session_not_ready")
        return self._finish_ctp_bundle_quote_reference_snapshot(
            preflight,
            results,
            errors,
            parsed_legs,
            quote_evidence=quote_evidence,
            request_count_delta=request_count_delta,
            write_request_free=write_request_free,
            scope=scope,
            current_session=session_after,
            request_ids=request_ids,
        )

    def _finish_ctp_bundle_quote_reference_snapshot(
        self,
        preflight: Mapping[str, Any],
        results: Mapping[str, Any],
        errors: Iterable[str],
        parsed_legs: Iterable[Mapping[str, Any]],
        *,
        quote_evidence: Optional[Mapping[int, Mapping[str, Any]]] = None,
        request_count_delta: Optional[Mapping[str, int]] = None,
        write_request_free: bool = False,
        scope: Optional[Mapping[str, Any]] = None,
        current_session: Optional[Mapping[str, Any]] = None,
        request_ids: Optional[Mapping[str, int]] = None,
    ) -> Dict[str, Any]:
        """Return a credential-safe, quote-only result regardless of failure mode."""
        quote_evidence = quote_evidence or {}
        canonical_legs = []
        for index, leg in enumerate(parsed_legs):
            quote = quote_evidence.get(index, {})
            canonical_legs.append(
                {
                    "instrument_id": leg["instrument_id"],
                    "exchange_id": leg["exchange_id"],
                    "bid_price": quote.get("bid_price"),
                    "ask_price": quote.get("ask_price"),
                    "bid_volume": quote.get("bid_volume"),
                    "ask_volume": quote.get("ask_volume"),
                    "entry_buy_price": quote.get("entry_buy_price"),
                    "exit_sell_price": quote.get("exit_sell_price"),
                    "requested_at_utc": quote.get("requested_at_utc"),
                    "received_at_utc": quote.get("received_at_utc"),
                    "requested_monotonic": quote.get("requested_monotonic"),
                    "received_monotonic": quote.get("received_monotonic"),
                    "request_id": quote.get("request_id"),
                }
            )
        snapshot = {
            "schema_version": "backtrader.ctp.bundle-quote-reference.v1",
            "read_only": True,
            "quote_only": True,
            "execution_eligible": False,
            "bundle_preflight": deepcopy(dict(preflight)),
            "bundle_scope": deepcopy(dict(scope or {})),
            "current_session": deepcopy(_redact_diagnostic(current_session or {})),
            "query_results": deepcopy(dict(results)),
            "legs": canonical_legs,
            "request_ids": deepcopy(dict(request_ids or {})),
            "request_count_delta": deepcopy(dict(request_count_delta or {})),
            "write_request_free": write_request_free,
            "evidence_errors": sorted({str(item) for item in errors}),
        }
        snapshot["evidence_complete"] = bool(
            not snapshot["evidence_errors"] and write_request_free and len(canonical_legs) == 3
        )
        snapshot["complete"] = snapshot["evidence_complete"]
        snapshot["read_only_safe"] = bool(
            snapshot["evidence_complete"]
            and preflight.get("read_only_safe") is True
            and preflight.get("write_request_free") is True
        )
        snapshot["snapshot_sha256"] = self._ctp_bundle_snapshot_sha256(snapshot)
        return snapshot

    def get_ctp_bundle_execution_reference_snapshot(
        self,
        legs: Any,
        *,
        primary_leg: Any = None,
        primary_instrument_id: Any = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Return read-only executable quotes and typed option-cost evidence.

        The existing bundle preflight is the mandatory Stage-A gate.  This
        method only adds depth and reference-cost queries through that same
        managed client; it never confirms settlement, arms execution, or
        submits/cancels an order.  A price in this snapshot is evidence, not a
        fill or an execution authorization.
        """
        raw_legs = list(legs) if not isinstance(legs, (list, tuple)) else list(legs)
        preflight = self.get_ctp_bundle_preflight_snapshot(
            raw_legs,
            primary_leg=primary_leg,
            primary_instrument_id=primary_instrument_id,
            timeout=timeout,
            read_only=True,
        )
        errors = list(preflight.get("evidence_errors") or [])
        if (
            preflight.get("evidence_complete") is not True
            or preflight.get("read_only_safe") is not True
        ):
            return self._finish_ctp_execution_reference_snapshot(
                preflight, {}, errors + ["bundle_preflight_not_safe"]
            )
        parsed_legs = self._normalise_ctp_bundle_legs(
            raw_legs, primary_leg=primary_leg, primary_instrument_id=primary_instrument_id
        )
        session = preflight.get("session_after") or preflight.get("session") or {}
        expected_generation = session.get("connection_generation")
        expected_account = str(session.get("account_fingerprint") or "")
        expected_day = str(session.get("trading_day") or "")
        if not expected_account or not expected_day or not expected_generation:
            return self._finish_ctp_execution_reference_snapshot(
                preflight, {}, errors + ["execution_reference_session_identity_missing"]
            )
        before_session = self._read_ctp_session_state()
        before_counts = self._ctp_request_counts(before_session)
        started = time.monotonic()
        # Rate-limit every reference query against the caller's total budget;
        # reserving with a None deadline collapses the slot to a zero timeout
        # and turns flow-control waits into spurious query timeouts.
        total_timeout = max(float(timeout), 0.0)
        deadline = started + total_timeout if total_timeout > 0 else None
        targets = self._ctp_query_targets()
        target = targets[0] if targets else None
        results: Dict[str, Dict[str, Any]] = {}
        request_windows: Dict[str, Tuple[Any, Any]] = {}

        def run(label: str, request_type: str, method_name: str, kwargs: Mapping[str, Any]) -> None:
            sent_at = _dt.datetime.now(_UTC)
            sent_mono = time.monotonic()
            if target is None:
                result = self._ctp_query_failure(
                    request_type, before_session, "query_capability_unavailable"
                )
            else:
                try:
                    slot = self._reserve_ctp_query_slot(deadline)
                    result = self._normalise_ctp_query_result(
                        self._invoke_ctp_query(
                            target, request_type, method_name, timeout=slot or 0.0, kwargs=kwargs
                        ),
                        request_type,
                    )
                except Exception as exc:
                    result = self._ctp_query_failure(
                        request_type, before_session, type(exc).__name__
                    )
            received_at = _dt.datetime.now(_UTC)
            result["requested_at_utc"] = sent_at.isoformat()
            result["received_at_utc"] = received_at.isoformat()
            result["requested_monotonic"] = sent_mono
            result["received_monotonic"] = time.monotonic()
            results[label] = result
            request_windows[label] = (sent_at, received_at)

        for index, leg in enumerate(parsed_legs):
            run(
                f"leg[{index}].depth_market_data",
                "depth_market_data",
                "query_depth_market_data_result",
                {"instrument_id": leg["instrument_id"], "exchange_id": leg["exchange_id"]},
            )
        leg_metadata = [item.get("metadata") or {} for item in preflight.get("legs", [])]
        prices: Dict[int, float] = {}
        quotes: Dict[int, Dict[str, Any]] = {}
        for index, leg in enumerate(parsed_legs):
            result = results.get(f"leg[{index}].depth_market_data", {})
            record, local_errors = self._ctp_execution_reference_record(
                result.get("records"), leg, label=f"leg[{index}].depth_market_data"
            )
            errors.extend(local_errors)
            quote, price_errors = self._ctp_execution_reference_quote(
                record, label=f"leg[{index}].depth_market_data"
            )
            errors.extend(price_errors)
            if quote is not None:
                quotes[index] = {
                    **quote,
                    "instrument_id": leg["instrument_id"],
                    "exchange_id": leg["exchange_id"],
                    "entry_buy_price": quote["ask_price"],
                    "exit_sell_price": quote["bid_price"],
                    "requested_at_utc": result.get("requested_at_utc"),
                    "received_at_utc": result.get("received_at_utc"),
                    "requested_monotonic": result.get("requested_monotonic"),
                    "received_monotonic": result.get("received_monotonic"),
                }
                # Cost input is the executable entry side, never an arbitrary
                # lattice price: buys bind to ask.
                prices[index] = quote["ask_price"]

        future_index = next(
            (
                index
                for index, metadata in enumerate(leg_metadata)
                if metadata.get("asset_type") == "future"
            ),
            None,
        )
        if future_index is None or future_index not in prices:
            errors.append("future_execution_price_unavailable")
        for index, metadata in enumerate(leg_metadata):
            if metadata.get("asset_type") != "option":
                continue
            option_price = prices.get(index)
            future_price = prices.get(future_index) if future_index is not None else None
            if option_price is None or future_price is None:
                errors.append(f"leg[{index}].option_trade_cost_input_unavailable")
                continue
            leg = parsed_legs[index]
            run(
                f"leg[{index}].option_trade_cost",
                "option_trade_cost",
                "query_option_instrument_trade_cost_result",
                {
                    "instrument_id": leg["instrument_id"],
                    "exchange_id": leg["exchange_id"],
                    "hedge_flag": "1",
                    "input_price": option_price,
                    "underlying_price": future_price,
                },
            )
            run(
                f"leg[{index}].option_commission_rate",
                "option_commission_rate",
                "query_option_instrument_commission_rate_result",
                {"instrument_id": leg["instrument_id"], "exchange_id": leg["exchange_id"]},
            )
            for field in ("option_trade_cost", "option_commission_rate"):
                result = results[f"leg[{index}].{field}"]
                if not self._ctp_query_result_complete(result):
                    errors.append(f"leg[{index}].{field}_query_incomplete")
                record, local_errors = self._ctp_execution_reference_record(
                    result.get("records"),
                    leg,
                    label=f"leg[{index}].{field}",
                    require_exchange=False,
                )
                errors.extend(local_errors)
                if record is None:
                    continue
                if field == "option_trade_cost":
                    errors.extend(
                        self._ctp_bundle_option_trade_cost_evidence_errors(
                            record, label=f"leg[{index}].option_trade_cost"
                        )
                    )
                else:
                    errors.extend(
                        self._ctp_bundle_commission_evidence_errors(
                            record, label=f"leg[{index}].option_commission_rate"
                        )
                    )

        after_session = self._read_ctp_session_state()
        after_counts = self._ctp_request_counts(after_session)
        delta = self._ctp_request_count_delta(before_counts, after_counts)
        write_free = bool(
            delta is not None and all(delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        if not write_free:
            errors.append("execution_reference_write_request_evidence_invalid")
        for label, result in results.items():
            if not self._ctp_query_result_complete(result):
                errors.append(f"{label}_query_incomplete")
            if result.get("schema_version") in (None, ""):
                errors.append(f"{label}_schema_version_missing")
            if result.get("account_fingerprint") != expected_account:
                errors.append(f"{label}_account_fingerprint_mismatch")
            if result.get("connection_generation") != expected_generation:
                errors.append(f"{label}_connection_generation_mismatch")
            if result.get("trading_day") != expected_day:
                errors.append(f"{label}_trading_day_mismatch")
            errors.extend(
                self._ctp_bundle_query_time_errors(
                    result,
                    label=label,
                    requested_at_utc=request_windows[label][0],
                    received_at_utc=request_windows[label][1],
                )
            )
        request_ids = [
            result.get("request_id")
            for result in results.values()
            if result.get("request_id") not in (None, "", 0, "0")
        ]
        if len(request_ids) != len(set(request_ids)):
            errors.append("execution_reference_request_id_not_unique")
        if (
            after_session.get("connection_generation") != expected_generation
            or after_session.get("trading_day") != expected_day
        ):
            errors.append("execution_reference_session_changed")
        broker_contract_metadata, metadata_errors = self._build_ctp_broker_contract_metadata(
            preflight, results, parsed_legs, prices, quotes
        )
        errors.extend(metadata_errors)
        return self._finish_ctp_execution_reference_snapshot(
            preflight,
            results,
            errors,
            request_count_delta=delta,
            write_request_free=write_free,
            prices=prices,
            broker_contract_metadata=broker_contract_metadata,
            quote_evidence=quotes,
            parsed_legs=parsed_legs,
        )

    def _build_ctp_broker_contract_metadata(
        self,
        preflight: Mapping[str, Any],
        results: Mapping[str, Any],
        parsed_legs: Iterable[Mapping[str, str]],
        prices: Mapping[int, float],
        quotes: Mapping[int, Mapping[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """Build broker input metadata solely from complete verified CTP records."""
        legs = list(parsed_legs)
        evidence = preflight.get("legs")
        if not isinstance(evidence, list) or len(evidence) != len(legs):
            return None, ["broker_contract_metadata_leg_evidence_missing"]
        errors: List[str] = []
        output: List[Dict[str, Any]] = []

        def number(
            row: Mapping[str, Any], names: Tuple[str, ...], label: str, positive: bool = False
        ):
            value, numeric_error = self._ctp_bundle_finite_numeric_aliases(row, names)
            if numeric_error is not None or value is None or (positive and value <= 0):
                errors.append(f"broker_contract_{label}_missing_or_invalid")
                return None
            return value

        generic_commission = (
            (("OpenRatioByMoney", "open_ratio_by_money"), "open_ratio_by_money"),
            (("OpenRatioByVolume", "open_ratio_by_volume"), "open_ratio_by_volume"),
            (("CloseRatioByMoney", "close_ratio_by_money"), "close_ratio_by_money"),
            (("CloseRatioByVolume", "close_ratio_by_volume"), "close_ratio_by_volume"),
            (
                ("CloseTodayRatioByMoney", "close_today_ratio_by_money"),
                "close_today_ratio_by_money",
            ),
            (
                ("CloseTodayRatioByVolume", "close_today_ratio_by_volume"),
                "close_today_ratio_by_volume",
            ),
        )
        generic_margin = (
            (
                ("LongMarginRatioByMoney", "long_margin_ratio_by_money"),
                "long_margin_ratio_by_money",
            ),
            (
                ("LongMarginRatioByVolume", "long_margin_ratio_by_volume"),
                "long_margin_ratio_by_volume",
            ),
            (
                ("ShortMarginRatioByMoney", "short_margin_ratio_by_money"),
                "short_margin_ratio_by_money",
            ),
            (
                ("ShortMarginRatioByVolume", "short_margin_ratio_by_volume"),
                "short_margin_ratio_by_volume",
            ),
        )
        option_cost_fields = (
            "FixedMargin",
            "MiniMargin",
            "Royalty",
            "ExchFixedMargin",
            "ExchMiniMargin",
        )
        for index, (leg, item) in enumerate(zip(legs, evidence)):
            instrument = item.get("instrument")
            metadata = item.get("metadata")
            if not isinstance(instrument, Mapping) or not isinstance(metadata, Mapping):
                errors.append(f"broker_contract_leg[{index}]_instrument_evidence_missing")
                continue
            if item.get("evidence_complete") is not True:
                errors.append(f"broker_contract_leg[{index}]_preflight_incomplete")
            if instrument.get("InstrumentID") != leg["instrument_id"]:
                errors.append(f"broker_contract_leg[{index}]_instrument_identity_mismatch")
            if instrument.get("ExchangeID") != leg["exchange_id"]:
                errors.append(f"broker_contract_leg[{index}]_exchange_identity_mismatch")
            tick = number(
                instrument,
                ("PriceTick", "price_tick", "tick_size"),
                f"leg[{index}]_price_tick",
                True,
            )
            multiplier = number(
                instrument,
                ("VolumeMultiple", "volume_multiple", "multiplier", "contract_size"),
                f"leg[{index}]_multiplier",
                True,
            )
            reference_price = prices.get(index)
            if (
                reference_price is None
                or not math.isfinite(float(reference_price))
                or reference_price <= 0
            ):
                errors.append(f"broker_contract_leg[{index}]_reference_price_missing_or_invalid")
            asset_type = metadata.get("asset_type")
            quote = quotes.get(index)
            if not isinstance(quote, Mapping):
                errors.append(f"broker_contract_leg[{index}]_quote_evidence_missing")
            commission_row = item.get("commission_rate")
            if asset_type == "option":
                commission_result = results.get(f"leg[{index}].option_commission_rate", {})
                commission_rows = (
                    commission_result.get("records")
                    if isinstance(commission_result, Mapping)
                    else None
                )
                commission_row, commission_errors = self._ctp_execution_reference_record(
                    commission_rows,
                    leg,
                    label=f"broker_contract_leg[{index}].option_commission_rate",
                    require_exchange=False,
                )
                errors.extend(commission_errors)
            commission: Dict[str, float] = {}
            if not isinstance(commission_row, Mapping):
                errors.append(f"broker_contract_leg[{index}]_commission_evidence_missing")
            else:
                for names, field in generic_commission:
                    value = number(commission_row, names, f"leg[{index}]_{field}")
                    if value is not None:
                        commission[field] = value
            margin: Dict[str, float] = {}
            if asset_type == "future":
                margin_row = item.get("margin_rate")
                if not isinstance(margin_row, Mapping):
                    errors.append(f"broker_contract_leg[{index}]_margin_evidence_missing")
                else:
                    for names, field in generic_margin:
                        value = number(margin_row, names, f"leg[{index}]_{field}")
                        if value is not None:
                            margin[field] = value
            elif asset_type != "option":
                errors.append(f"broker_contract_leg[{index}]_asset_type_invalid")
            entry = {
                "instrument_id": leg["instrument_id"],
                "exchange_id": leg["exchange_id"],
                "raw_instrument_id": instrument.get("InstrumentID"),
                "symbol_aliases": [
                    f"{leg['exchange_id']}.{leg['instrument_id']}",
                    leg["instrument_id"],
                ],
                "product_id": instrument.get("ProductID"),
                "asset_type": asset_type,
                "price_tick": tick,
                "multiplier": multiplier,
                "reference_price": reference_price,
                "bid_price": quote.get("bid_price") if isinstance(quote, Mapping) else None,
                "ask_price": quote.get("ask_price") if isinstance(quote, Mapping) else None,
                "bid_volume": quote.get("bid_volume") if isinstance(quote, Mapping) else None,
                "ask_volume": quote.get("ask_volume") if isinstance(quote, Mapping) else None,
                "entry_buy_price": quote.get("ask_price") if isinstance(quote, Mapping) else None,
                "exit_sell_price": quote.get("bid_price") if isinstance(quote, Mapping) else None,
                "quote_timing": (
                    {
                        key: quote.get(key)
                        for key in (
                            "requested_at_utc",
                            "received_at_utc",
                            "requested_monotonic",
                            "received_monotonic",
                        )
                    }
                    if isinstance(quote, Mapping)
                    else None
                ),
                "commission": commission,
            }
            if asset_type == "future":
                entry["margin"] = margin
            else:
                cost_result = results.get(f"leg[{index}].option_trade_cost", {})
                cost_rows = cost_result.get("records") if isinstance(cost_result, Mapping) else None
                cost, cost_errors = self._ctp_execution_reference_record(
                    cost_rows,
                    leg,
                    label=f"broker_contract_leg[{index}].option_trade_cost",
                    require_exchange=False,
                )
                errors.extend(cost_errors)
                option_cost: Dict[str, float] = {}
                if cost is None:
                    errors.append(f"broker_contract_leg[{index}]_option_cost_evidence_missing")
                else:
                    for field in option_cost_fields:
                        value = number(cost, (field,), f"leg[{index}]_option_{field.lower()}")
                        if value is not None:
                            option_cost[field] = value
                entry["option_premium"] = reference_price
                entry["option_trade_cost"] = option_cost
                entry["option_commission"] = commission
            output.append(entry)
        if errors:
            return None, sorted(set(errors))
        return {
            "schema_version": "backtrader.ctp.broker-contract-metadata.v1",
            "verified_from": "backtrader.ctp.bundle-execution-reference.v1",
            "read_only_evidence": True,
            "legs": output,
        }, []

    def _finish_ctp_execution_reference_snapshot(
        self,
        preflight: Mapping[str, Any],
        results: Mapping[str, Any],
        errors: Iterable[str],
        *,
        request_count_delta: Optional[Mapping[str, int]] = None,
        write_request_free: bool = False,
        prices: Optional[Mapping[int, float]] = None,
        broker_contract_metadata: Optional[Mapping[str, Any]] = None,
        quote_evidence: Optional[Mapping[int, Mapping[str, Any]]] = None,
        parsed_legs: Optional[Iterable[Mapping[str, str]]] = None,
    ) -> Dict[str, Any]:
        snapshot = {
            "schema_version": "backtrader.ctp.bundle-execution-reference.v1",
            "read_only": True,
            "execution_eligible": False,
            "bundle_preflight": deepcopy(dict(preflight)),
            "query_results": deepcopy(dict(results)),
            "prices": {str(key): value for key, value in (prices or {}).items()},
            "legs": [
                {
                    "instrument_id": leg["instrument_id"],
                    "exchange_id": leg["exchange_id"],
                    **dict((quote_evidence or {}).get(index, {})),
                }
                for index, leg in enumerate(parsed_legs or [])
            ],
            "broker_contract_metadata": (
                deepcopy(dict(broker_contract_metadata))
                if broker_contract_metadata is not None
                else None
            ),
            "request_count_delta": deepcopy(dict(request_count_delta or {})),
            "write_request_free": write_request_free,
            "evidence_errors": sorted({str(item) for item in errors}),
        }
        snapshot["evidence_complete"] = not snapshot["evidence_errors"] and write_request_free
        snapshot["broker_contract_metadata_complete"] = bool(
            snapshot["evidence_complete"] and snapshot["broker_contract_metadata"] is not None
        )
        if not snapshot["broker_contract_metadata_complete"]:
            snapshot["broker_contract_metadata"] = None
        snapshot["snapshot_sha256"] = self._ctp_bundle_snapshot_sha256(snapshot)
        return snapshot

    @staticmethod
    def _ctp_execution_reference_record(
        records: Any, leg: Mapping[str, str], *, label: str, require_exchange: bool = True
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        # Some CTP fronts (SimNow included) treat the InstrumentID query
        # filter as a prefix match and return the whole product chain.  The
        # signed leg identity is still enforced exactly: filter to the one
        # row whose InstrumentID equals the requested leg before applying
        # the single-record contract.
        if isinstance(records, list):
            exact_rows = [
                row
                for row in records
                if isinstance(row, Mapping)
                and str(row.get("InstrumentID", row.get("instrument_id", ""))).strip()
                == str(leg["instrument_id"]).strip()
            ]
        else:
            exact_rows = None
        if not isinstance(exact_rows, list) or len(exact_rows) != 1:
            return None, [f"{label}_record_not_exactly_one"]
        record = dict(exact_rows[0])
        errors: List[str] = []
        instruments = [record[name] for name in ("InstrumentID", "instrument_id") if name in record]
        exchanges = [record[name] for name in ("ExchangeID", "exchange_id") if name in record]
        if not instruments or (require_exchange and not exchanges):
            errors.append(f"{label}_identity_alias_missing")
        if not instruments or len(set(instruments)) > 1 or instruments[0] != leg["instrument_id"]:
            errors.append(f"{label}_instrument_identity_mismatch")
        # CZCE reference responses (option cost/commission in particular)
        # legitimately omit ExchangeID; the instrument identity plus the
        # scoped query request already fix the venue.  Only a contradictory
        # non-empty exchange value is a mismatch.
        if (
            exchanges
            and exchanges[0]
            and (len(set(exchanges)) > 1 or exchanges[0] != leg["exchange_id"])
        ):
            errors.append(f"{label}_exchange_identity_mismatch")
        return (record if not errors else None), sorted(set(errors))

    @classmethod
    def _ctp_execution_reference_quote(
        cls, record: Optional[Mapping[str, Any]], *, label: str
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        if record is None:
            return None, [f"{label}_quote_missing"]
        bid, bid_error = cls._ctp_bundle_finite_numeric_aliases(
            record, ("BidPrice1", "bid_price_1", "bid")
        )
        ask, ask_error = cls._ctp_bundle_finite_numeric_aliases(
            record, ("AskPrice1", "ask_price_1", "ask")
        )
        errors: List[str] = []
        if bid_error is not None or bid is None or not 0 < bid < 1e300:
            errors.append(f"{label}_bid_price_required")
        if ask_error is not None or ask is None or not 0 < ask < 1e300:
            errors.append(f"{label}_ask_price_required")
        if not errors and bid > ask:
            errors.append(f"{label}_bid_ask_crossed")
        volumes: Dict[str, Optional[float]] = {"bid_volume": None, "ask_volume": None}
        for field, names in (
            ("bid_volume", ("BidVolume1", "bid_volume_1", "bid_volume")),
            ("ask_volume", ("AskVolume1", "ask_volume_1", "ask_volume")),
        ):
            present = any(name in record and record[name] not in (None, "") for name in names)
            if present:
                value, value_error = cls._ctp_bundle_finite_numeric_aliases(record, names)
                volumes[field] = value
                if value_error is not None or value is None or value <= 0:
                    errors.append(f"{label}_{field}_positive_required")
        if (volumes["bid_volume"] is None) != (volumes["ask_volume"] is None):
            errors.append(f"{label}_quote_volume_pair_required")
        if errors:
            return None, sorted(set(errors))
        return {
            "bid_price": bid,
            "ask_price": ask,
            "bid_volume": volumes["bid_volume"],
            "ask_volume": volumes["ask_volume"],
        }, []

    @classmethod
    def _ctp_execution_reference_price(
        cls, record: Optional[Mapping[str, Any]], *, label: str
    ) -> Tuple[Optional[float], List[str]]:
        """Compatibility helper; execution-reference snapshots require both sides."""
        quote, errors = cls._ctp_execution_reference_quote(record, label=label)
        return (quote["ask_price"] if quote is not None else None), errors

    def get_ctp_reconciliation_snapshot(self, *, timeout: float = 5.0) -> Dict[str, Any]:
        """Query account/positions/orders/trades with terminal completion evidence."""
        snapshot = self._build_ctp_query_snapshot(
            instrument_id=None,
            exchange_id="",
            product_id="",
            timeout=max(float(timeout), 0.0),
            include_reference_data=False,
            read_only=False,
        )
        snapshot["schema_version"] = "backtrader.ctp.reconciliation.v1"
        self._last_ctp_reconciliation_snapshot = deepcopy(snapshot)
        return snapshot

    def prepare_ctp_settlement(self, *, timeout: float = 5.0) -> Dict[str, Any]:
        """Explicitly confirm CTP settlement and return before/after request evidence."""
        if not self._is_ctp_session_provider():
            raise BtApiStoreError("CTP settlement preparation requires a CTP provider")
        self._ensure_api_ready()
        before = self._read_ctp_session_state()
        before_counts = self._ctp_request_counts(before)
        provider = str(self.provider or "").strip().lower()
        method = None
        kwargs: Dict[str, Any] = {"timeout": max(float(timeout), 0.0)}
        if provider == "btapi":
            method = getattr(self._api, "confirm_ctp_settlement", None)
            kwargs["exchange_name"] = self._ctp_sdk_exchange_name()
        else:
            for target in self._ctp_query_targets():
                candidate = getattr(target, "confirm_settlement", None)
                if callable(candidate):
                    method = candidate
                    break
        success = False
        error_code = None
        if not callable(method):
            error_code = "settlement_confirmation_capability_unavailable"
        else:
            try:
                success = bool(method(**kwargs))
            except Exception as exc:
                error_code = type(exc).__name__
        after = self._read_ctp_session_state()
        after_counts = self._ctp_request_counts(after)
        delta = self._ctp_request_count_delta(before_counts, after_counts)
        settlement_delta = delta.get("settlement_confirm") if delta is not None else None
        order_insert_delta = delta["order_insert"] if delta is not None else None
        order_action_delta = delta["order_action"] if delta is not None else None
        confirmed = str(after.get("settlement_state") or "").strip().lower() == "confirmed"
        evidence_complete = bool(
            success
            and confirmed
            and settlement_delta == 1
            and order_insert_delta == 0
            and order_action_delta == 0
        )
        if not evidence_complete and error_code is None:
            error_code = "settlement_confirmation_evidence_incomplete"
        return {
            "schema_version": "backtrader.ctp.settlement-preparation.v1",
            "exchange_name": self._ctp_sdk_exchange_name() if provider == "btapi" else "CTP",
            "success": success,
            "evidence_complete": evidence_complete,
            "error_code": error_code,
            "before_session": deepcopy(_redact_diagnostic(before)),
            "after_session": deepcopy(_redact_diagnostic(after)),
            "request_counts_before": before_counts,
            "request_counts_after": after_counts,
            "request_count_delta": delta,
            "settlement_confirm_delta": settlement_delta,
            "order_insert_delta": order_insert_delta,
            "order_action_delta": order_action_delta,
        }

    def verify_ctp_settlement(self, *, timeout: float = 5.0) -> Dict[str, Any]:
        """Verify existing settlement state using a read-only server query."""
        if not self._is_ctp_session_provider():
            raise BtApiStoreError("CTP settlement verification requires a CTP provider")
        self._ensure_api_ready()
        before = self._read_ctp_session_state()
        before_counts = self._ctp_request_counts(before)
        provider = str(self.provider or "").strip().lower()
        method = None
        kwargs: Dict[str, Any] = {"timeout": max(float(timeout), 0.0)}
        if provider == "btapi":
            method = getattr(self._api, "verify_ctp_settlement", None)
            kwargs["exchange_name"] = self._ctp_sdk_exchange_name()
        else:
            for target in self._ctp_query_targets():
                candidate = getattr(target, "verify_settlement_confirmation", None)
                if callable(candidate):
                    method = candidate
                    break
        if callable(method):
            try:
                result = self._normalise_ctp_query_result(
                    method(**kwargs), "settlement_confirmation"
                )
            except Exception as exc:
                result = self._ctp_query_failure(
                    "settlement_confirmation", before, type(exc).__name__
                )
        else:
            result = self._ctp_query_failure(
                "settlement_confirmation",
                before,
                "settlement_verification_capability_unavailable",
            )
        after = self._read_ctp_session_state()
        after_counts = self._ctp_request_counts(after)
        delta = self._ctp_request_count_delta(before_counts, after_counts)
        write_request_free = bool(
            delta is not None and all(delta[name] == 0 for name in _CTP_WRITE_REQUEST_TYPES)
        )
        session_confirmed = bool(
            str(after.get("settlement_state") or "").strip().lower() == "confirmed"
            and after.get("trading_ready") is True
        )
        evidence_complete = bool(
            self._ctp_query_result_complete(result) and write_request_free and session_confirmed
        )
        error_code = None
        if not evidence_complete:
            error_code = result.get("error_code") or "settlement_verification_evidence_incomplete"
        return {
            "schema_version": "backtrader.ctp.settlement-verification.v1",
            "exchange_name": self._ctp_sdk_exchange_name() if provider == "btapi" else "CTP",
            "query_result": deepcopy(result),
            "complete": evidence_complete,
            "is_last_seen": result.get("is_last_seen") is True,
            "timed_out": bool(result.get("timed_out")),
            "error_code": error_code,
            "evidence_complete": evidence_complete,
            "read_only_safe": write_request_free,
            "before_session": deepcopy(_redact_diagnostic(before)),
            "after_session": deepcopy(_redact_diagnostic(after)),
            "request_counts_before": before_counts,
            "request_counts_after": after_counts,
            "request_count_delta": delta,
        }

    def get_ctp_query_health(self) -> Dict[str, Any]:
        """Return cached query evidence only while it matches the live CTP session."""
        snapshot = self._last_ctp_preflight_snapshot
        if snapshot is None:
            return {
                "supported": self.supports_complete_ctp_queries(include_reference_data=True),
                "evidence_complete": False,
                "evidence_errors": ["ctp_query_snapshot_missing"],
            }
        health = deepcopy(snapshot)
        errors = set(health.get("evidence_errors") or ())
        current = self._read_ctp_session_state()

        def positive_generation(value: Any) -> int:
            if isinstance(value, bool):
                return 0
            try:
                parsed = int(value or 0)
            except (TypeError, ValueError):
                return 0
            return parsed if parsed > 0 else 0

        snapshot_generation = positive_generation(health.get("connection_generation"))
        current_generation = positive_generation(current.get("connection_generation"))
        snapshot_account = str(health.get("account_fingerprint") or "").strip()
        current_account = str(current.get("account_fingerprint") or "").strip()
        snapshot_trading_day = str(health.get("trading_day") or "").strip()
        current_trading_day = str(current.get("trading_day") or "").strip()
        if current_generation <= 0:
            errors.add("current_session_generation_missing")
        elif snapshot_generation != current_generation:
            errors.add("ctp_query_snapshot_generation_stale")
        if not current_account:
            errors.add("current_session_account_fingerprint_missing")
        elif snapshot_account != current_account:
            errors.add("ctp_query_snapshot_account_stale")
        if not current_trading_day:
            errors.add("current_session_trading_day_missing")
        elif snapshot_trading_day != current_trading_day:
            errors.add("ctp_query_snapshot_trading_day_stale")
        if current.get("read_only_ready") is not True and current.get("ready") is not True:
            errors.add("current_ctp_session_not_ready")

        completed = health.get("completed_monotonic")
        try:
            age = time.monotonic() - float(completed)
        except (TypeError, ValueError, OverflowError):
            age = math.inf
        if not math.isfinite(age) or age < 0:
            errors.add("ctp_query_snapshot_clock_invalid")
        elif age > self._ctp_query_max_age_seconds:
            errors.add("ctp_query_snapshot_stale")
        health["age_seconds"] = age
        health["current_session"] = deepcopy(_redact_diagnostic(current))
        health["supported"] = self.supports_complete_ctp_queries(include_reference_data=True)
        health["evidence_errors"] = sorted(errors)
        health["evidence_complete"] = bool(snapshot.get("evidence_complete") is True and not errors)
        return health

    def get_ctp_session_state(self) -> Dict[str, Any]:
        """Return cached SDK/native CTP session evidence without starting a query."""
        if not self._is_ctp_session_provider():
            raise BtApiStoreError("CTP session state requires a CTP provider")
        if self._api is None:
            return {
                "connected": False,
                "read_only_ready": False,
                "trading_ready": False,
                "request_counts": {},
            }
        return deepcopy(_redact_diagnostic(self._read_ctp_session_state()))

    @staticmethod
    def _sha256_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _require_sha256(value: Any, field: str) -> str:
        text = str(value or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", text) is None:
            raise BtApiStoreError(f"CTP execution authorization {field} is invalid")
        return text

    @staticmethod
    def _is_sha256_hex(value: Any) -> bool:
        return re.fullmatch(r"[0-9a-f]{64}", str(value or "")) is not None

    @staticmethod
    def _authorization_utc(value: Any, field: str) -> _dt.datetime:
        try:
            parsed = _dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise BtApiStoreError(f"CTP execution authorization {field} is invalid")
        return parsed.astimezone(_UTC)

    @staticmethod
    def _authorization_query_ids(
        value: Any, expected_names: Tuple[str, ...], field: str
    ) -> Dict[str, int]:
        if not isinstance(value, Mapping) or set(value) != set(expected_names):
            raise BtApiStoreError(f"CTP execution authorization {field} is invalid")
        result: Dict[str, int] = {}
        for name in expected_names:
            request_id = value[name]
            if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id <= 0:
                raise BtApiStoreError(f"CTP execution authorization {field} is invalid")
            result[name] = request_id
        if len(set(result.values())) != len(result):
            raise BtApiStoreError(f"CTP execution authorization {field} is invalid")
        return result

    @staticmethod
    def _snapshot_query_ids(
        snapshot: Mapping[str, Any], names: Tuple[str, ...]
    ) -> Optional[Dict[str, int]]:
        query_results = snapshot.get("query_results")
        if not isinstance(query_results, Mapping):
            return None
        result: Dict[str, int] = {}
        for name in names:
            item = query_results.get(name)
            if not isinstance(item, Mapping) or not BtApiStore._ctp_query_result_complete(item):
                return None
            request_id = item.get("request_id")
            if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id <= 0:
                return None
            result[name] = request_id
        return result

    @staticmethod
    def _ctp_monotonic_clock_errors(
        snapshot: Mapping[str, Any], *, label: str, now: Optional[float] = None
    ) -> List[str]:
        """Validate one Store-local monotonic evidence envelope.

        ``started_monotonic`` and ``completed_monotonic`` are deliberately
        checked independently for every snapshot.  They are local
        ``time.monotonic`` values, so a value from another clock domain is
        treated as untrusted even when it happens to be numerically recent.
        """
        errors: List[str] = []
        try:
            current = time.monotonic() if now is None else float(now)
        except (TypeError, ValueError, OverflowError):
            return [f"{label}_clock_now_invalid"]
        if not math.isfinite(current) or current < 0:
            return [f"{label}_clock_now_invalid"]

        values: Dict[str, float] = {}
        for field in ("started_monotonic", "completed_monotonic"):
            raw = snapshot.get(field) if isinstance(snapshot, Mapping) else None
            if isinstance(raw, bool):
                errors.append(f"{label}_{field}_invalid")
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{label}_{field}_invalid")
                continue
            if not math.isfinite(value) or value < 0:
                errors.append(f"{label}_{field}_invalid")
                continue
            values[field] = value

        started = values.get("started_monotonic")
        completed = values.get("completed_monotonic")
        max_age_value: Optional[float] = None
        if "_ctp_query_max_age_seconds" in snapshot:
            max_age = snapshot.get("_ctp_query_max_age_seconds")
            try:
                max_age_value = float(max_age)
            except (TypeError, ValueError, OverflowError):
                max_age_value = math.inf
            if not math.isfinite(max_age_value) or max_age_value < 0:
                errors.append(f"{label}_max_age_invalid")
                max_age_value = None
        if started is not None:
            started_age = current - started
            if started_age >= 0 and max_age_value is not None and started_age > max_age_value:
                errors.append(f"{label}_started_stale")
        if started is not None and started > current:
            errors.append(f"{label}_started_monotonic_future")
        if completed is not None:
            age = current - completed
            if age < 0:
                errors.append(f"{label}_completed_monotonic_future")
            elif max_age_value is not None and age > max_age_value:
                errors.append(f"{label}_stale")
        if started is not None and completed is not None and completed < started:
            errors.append(f"{label}_completed_before_started")
        return sorted(set(errors))

    def _validate_ctp_snapshot_clock(self, snapshot: Mapping[str, Any], *, label: str) -> None:
        """Reject a snapshot whose monotonic age cannot be trusted."""
        if not isinstance(snapshot, Mapping):
            raise BtApiStoreError(f"CTP {label} snapshot clock is invalid")
        checked = dict(snapshot)
        checked["_ctp_query_max_age_seconds"] = self._ctp_query_max_age_seconds
        errors = self._ctp_monotonic_clock_errors(checked, label=label)
        if errors:
            raise BtApiStoreError(f"CTP {label} snapshot clock is invalid: {','.join(errors)}")

    @classmethod
    def _ctp_bundle_query_time_errors(
        cls,
        result: Mapping[str, Any],
        *,
        label: str,
        requested_at_utc: Any,
        received_at_utc: Any,
    ) -> List[str]:
        """Keep one direct-query result inside its Store-owned request window.

        The CTP SDK and this Store run in one process and sample the same host
        clock.  ``requested_at_utc``/``received_at_utc`` are therefore hard
        boundaries, rather than estimates that may be widened by a guessed
        tolerance.  The monotonic pair is sampled by the Store alongside the
        wall-clock pair and is checked independently for local clock rollback.
        """
        errors: List[str] = []
        started = cls._ctp_bundle_parse_utc_timestamp(result.get("started_at_utc"))
        completed = cls._ctp_bundle_parse_utc_timestamp(result.get("completed_at_utc"))
        requested = cls._ctp_bundle_parse_utc_timestamp(requested_at_utc)
        received = cls._ctp_bundle_parse_utc_timestamp(received_at_utc)
        if started is None:
            errors.append(f"{label}_started_at_utc_invalid")
        if completed is None:
            errors.append(f"{label}_completed_at_utc_invalid")
        if requested is None:
            errors.append(f"{label}_requested_at_utc_invalid")
        if received is None:
            errors.append(f"{label}_received_at_utc_invalid")
        if started is not None and completed is not None and completed < started:
            errors.append(f"{label}_completed_before_query_started")
        if requested is not None and received is not None:
            if received < requested:
                errors.append(f"{label}_received_before_request_sent")
            if started is not None and started < requested:
                errors.append(f"{label}_started_before_request_window")
            if completed is not None and completed < requested:
                errors.append(f"{label}_completed_before_request_sent")
            if started is not None and started > received:
                errors.append(f"{label}_started_after_receive_window")
            if completed is not None and completed > received:
                errors.append(f"{label}_completed_after_receive_window")

        monotonic_values: Dict[str, float] = {}
        for field in ("requested_monotonic", "received_monotonic"):
            raw = result.get(field)
            if isinstance(raw, bool):
                errors.append(f"{label}_{field}_invalid")
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{label}_{field}_invalid")
                continue
            if not math.isfinite(value) or value < 0:
                errors.append(f"{label}_{field}_invalid")
                continue
            monotonic_values[field] = value
        requested_monotonic = monotonic_values.get("requested_monotonic")
        received_monotonic = monotonic_values.get("received_monotonic")
        if (
            requested_monotonic is not None
            and received_monotonic is not None
            and received_monotonic < requested_monotonic
        ):
            errors.append(f"{label}_received_monotonic_before_request")
        return sorted(set(errors))

    @staticmethod
    def _normalized_account_fingerprint(value: Any) -> str:
        account = str(value or "").strip().lower()
        return account if account.startswith("acct_") else f"acct_{account}" if account else ""

    @staticmethod
    def _canonical_ctp_bundle_instrument(value: Any, exchange_id: Any = None) -> str:
        """Return one exact raw CTP bundle identity without V1 rewriting.

        CTP option identifiers may contain hyphens and lower-case product
        letters.  The V2 scope therefore keeps the native instrument spelling
        and only qualifies it with the exact upper-case exchange code.
        """
        if not isinstance(value, str) or not value or value != value.strip():
            return ""
        supplied_exchange = exchange_id
        if supplied_exchange not in (None, ""):
            if not isinstance(supplied_exchange, str) or supplied_exchange not in _CTP_EXCHANGES:
                return ""
        parts = value.split(".")
        if len(parts) == 1:
            exchange = supplied_exchange
            instrument = parts[0]
        elif len(parts) == 2:
            left, right = parts
            left_is_exchange = left in _CTP_EXCHANGES
            right_is_exchange = right in _CTP_EXCHANGES
            if left_is_exchange == right_is_exchange:
                return ""
            exchange = left if left_is_exchange else right
            instrument = right if left_is_exchange else left
            if supplied_exchange not in (None, "") and supplied_exchange != exchange:
                return ""
        else:
            return ""
        if not exchange or len(instrument) > 80:
            return ""
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", instrument) is None or not any(
            character.isdigit() for character in instrument
        ):
            return ""
        return f"{exchange}.{instrument}"

    @classmethod
    def _normalise_ctp_execution_proof(
        cls, proof: Mapping[str, Any], *, operation: str
    ) -> Tuple[Dict[str, Any], bool]:
        """Validate the closed V1 or exact V2 proof shape used by SDK calls."""
        if not isinstance(proof, Mapping):
            raise BtApiStoreError(f"SDK execution {operation} proof has an invalid shape")
        fields = set(proof)
        if fields == _CTP_EXECUTION_ARM_FIELDS:
            return deepcopy(dict(proof)), False
        if fields != _CTP_EXECUTION_ARM_BUNDLE_FIELDS:
            raise BtApiStoreError(f"SDK execution {operation} proof has an invalid shape")
        normalized = deepcopy(dict(proof))
        if normalized.get("scope_version") != _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION:
            raise BtApiStoreError(f"SDK execution {operation} bundle scope_version is invalid")
        instrument = cls._canonical_ctp_bundle_instrument(normalized.get("instrument"))
        if not instrument or normalized.get("instrument") != instrument:
            raise BtApiStoreError(f"SDK execution {operation} bundle instrument is invalid")
        authorized = normalized.get("authorized_instruments")
        if not isinstance(authorized, (list, tuple)) or not 2 <= len(authorized) <= 3:
            raise BtApiStoreError(f"SDK execution {operation} authorized_instruments is invalid")
        canonical = [cls._canonical_ctp_bundle_instrument(item) for item in authorized]
        if (
            any(not item for item in canonical)
            or list(authorized) != canonical
            or canonical != sorted(canonical)
            or len(set(canonical)) != len(canonical)
            or len({item.partition(".")[0] for item in canonical}) != 1
            or instrument not in canonical
        ):
            raise BtApiStoreError(f"SDK execution {operation} authorized_instruments is invalid")
        normalized["authorized_instruments"] = canonical
        return normalized, True

    @classmethod
    def _ctp_bundle_snapshot_scope(cls, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        """Extract and validate the exact scope represented by bundle evidence."""
        if not isinstance(snapshot, Mapping):
            raise BtApiStoreError("CTP bundle preflight snapshot is invalid")
        if snapshot.get("schema_version") != "backtrader.ctp.bundle-preflight.v2":
            raise BtApiStoreError("CTP bundle preflight schema is invalid")
        if snapshot.get("read_only") is not True or snapshot.get("read_only_safe") is not True:
            raise BtApiStoreError("CTP bundle preflight was not read-only")
        if snapshot.get("write_request_free") is not True:
            raise BtApiStoreError("CTP bundle preflight write evidence is invalid")
        if snapshot.get("evidence_complete") is not True or snapshot.get("complete") is not True:
            raise BtApiStoreError("CTP bundle preflight evidence is incomplete")
        if snapshot.get("evidence_errors"):
            raise BtApiStoreError("CTP bundle preflight evidence contains errors")
        snapshot_hash = snapshot.get("snapshot_sha256")
        if not cls._is_sha256_hex(
            snapshot_hash
        ) or snapshot_hash != cls._ctp_bundle_snapshot_sha256(snapshot):
            raise BtApiStoreError("CTP bundle preflight snapshot hash is invalid")
        raw_legs = snapshot.get("legs")
        if not isinstance(raw_legs, list) or len(raw_legs) not in {2, 3}:
            raise BtApiStoreError("CTP bundle preflight leg evidence is invalid")
        authorized = []
        primary = []
        for leg in raw_legs:
            if not isinstance(leg, Mapping):
                raise BtApiStoreError("CTP bundle preflight leg evidence is invalid")
            exchange_id = leg.get("exchange_id")
            instrument_id = leg.get("instrument_id")
            qualified = cls._canonical_ctp_bundle_instrument(instrument_id, exchange_id)
            if not qualified or qualified != f"{exchange_id}.{instrument_id}":
                raise BtApiStoreError("CTP bundle preflight leg identity is invalid")
            if leg.get("evidence_complete") is not True:
                raise BtApiStoreError("CTP bundle preflight leg evidence is incomplete")
            authorized.append(qualified)
            if leg.get("is_primary") is True:
                primary.append(qualified)
            elif leg.get("is_primary") not in (False, None):
                raise BtApiStoreError("CTP bundle preflight primary marker is invalid")
        if len(set(authorized)) != len(authorized) or len(primary) != 1:
            raise BtApiStoreError("CTP bundle preflight leg scope is invalid")
        if authorized != sorted(authorized):
            # The snapshot retains query order for diagnostics.  The signed
            # proof uses the SDK's canonical sorted order below.
            authorized = sorted(authorized)
        query_results = snapshot.get("query_results")
        if not isinstance(query_results, Mapping) or not query_results:
            raise BtApiStoreError("CTP bundle preflight query evidence is missing")
        complete_results = [item for item in query_results.values() if isinstance(item, Mapping)]
        if len(complete_results) != len(query_results) or any(
            not cls._ctp_query_result_complete(item) for item in complete_results
        ):
            raise BtApiStoreError("CTP bundle preflight query evidence is incomplete")
        generations = {item.get("connection_generation") for item in complete_results}
        accounts = {
            cls._normalized_account_fingerprint(item.get("account_fingerprint"))
            for item in complete_results
        }
        if len(generations) != 1 or len(accounts) != 1 or not next(iter(accounts), ""):
            raise BtApiStoreError("CTP bundle preflight query identity is inconsistent")
        snapshot_generation = snapshot.get("connection_generation")
        if generations != {snapshot_generation}:
            raise BtApiStoreError("CTP bundle preflight generation is inconsistent")
        snapshot_account = cls._normalized_account_fingerprint(snapshot.get("account_fingerprint"))
        if accounts != {snapshot_account}:
            raise BtApiStoreError("CTP bundle preflight account is inconsistent")
        return {
            "instrument": primary[0],
            "authorized_instruments": authorized,
            "connection_generation": snapshot_generation,
            "account_fingerprint": snapshot_account,
            "trading_day": snapshot.get("trading_day"),
            "exchange_id": primary[0].partition(".")[0],
        }

    def _get_ctp_bundle_query_health(self) -> Dict[str, Any]:
        """Return V2 bundle evidence only while it matches the live session."""
        snapshot = self._last_ctp_bundle_preflight_snapshot
        if snapshot is None:
            return {
                "supported": self.supports_complete_ctp_queries(include_reference_data=True),
                "evidence_complete": False,
                "evidence_errors": ["ctp_bundle_query_snapshot_missing"],
            }
        health = deepcopy(snapshot)
        errors = set(health.get("evidence_errors") or ())
        try:
            self._validate_ctp_snapshot_clock(health, label="bundle_preflight")
        except BtApiStoreError:
            errors.add("ctp_bundle_query_snapshot_clock_invalid")
        try:
            scope = self._ctp_bundle_snapshot_scope(health)
        except BtApiStoreError:
            scope = {}
            errors.add("ctp_bundle_snapshot_invalid")
        current = self._read_ctp_session_state()
        try:
            current_generation = int(current.get("connection_generation") or 0)
        except (TypeError, ValueError):
            current_generation = 0
        snapshot_generation = scope.get("connection_generation")
        if current_generation <= 0:
            errors.add("current_session_generation_missing")
        elif current_generation != snapshot_generation:
            errors.add("ctp_bundle_query_snapshot_generation_stale")
        current_account = self._normalized_account_fingerprint(current.get("account_fingerprint"))
        if not current_account:
            errors.add("current_session_account_fingerprint_missing")
        elif current_account != scope.get("account_fingerprint"):
            errors.add("ctp_bundle_query_snapshot_account_stale")
        current_day = str(current.get("trading_day") or "").strip()
        if not current_day:
            errors.add("current_session_trading_day_missing")
        elif current_day != str(scope.get("trading_day") or "").strip():
            errors.add("ctp_bundle_query_snapshot_trading_day_stale")
        if current.get("read_only_ready") is not True and current.get("ready") is not True:
            errors.add("current_ctp_session_not_ready")
        completed = health.get("completed_monotonic")
        try:
            age = time.monotonic() - float(completed)
        except (TypeError, ValueError, OverflowError):
            age = math.inf
        if not math.isfinite(age) or age < 0:
            errors.add("ctp_bundle_query_snapshot_clock_invalid")
        elif age > self._ctp_query_max_age_seconds:
            errors.add("ctp_bundle_query_snapshot_stale")
        health["age_seconds"] = age
        health["current_session"] = deepcopy(_redact_diagnostic(current))
        health["bundle_scope"] = scope
        health["supported"] = self.supports_complete_ctp_queries(include_reference_data=True)
        health["evidence_errors"] = sorted(errors)
        health["evidence_complete"] = bool(snapshot.get("evidence_complete") is True and not errors)
        return health

    @classmethod
    def _validate_bundle_scope_against_snapshot(
        cls, proof: Mapping[str, Any], snapshot: Mapping[str, Any]
    ) -> Dict[str, Any]:
        scope = cls._ctp_bundle_snapshot_scope(snapshot)
        if proof.get("instrument") != scope["instrument"]:
            raise BtApiStoreError("CTP bundle proof primary instrument does not match preflight")
        if list(proof.get("authorized_instruments") or ()) != scope["authorized_instruments"]:
            raise BtApiStoreError("CTP bundle proof authorized scope does not match preflight")
        if (
            cls._normalized_account_fingerprint(proof.get("account_fingerprint"))
            != scope["account_fingerprint"]
        ):
            raise BtApiStoreError("CTP bundle proof account does not match preflight")
        if proof.get("trading_day") != scope.get("trading_day"):
            raise BtApiStoreError("CTP bundle proof trading_day does not match preflight")
        if proof.get("connection_generation") != scope.get("connection_generation"):
            raise BtApiStoreError("CTP bundle proof generation does not match preflight")
        session = snapshot.get("session_after") or snapshot.get("session") or {}
        if not isinstance(session, Mapping) or proof.get("environment_profile") != session.get(
            "environment_profile"
        ):
            raise BtApiStoreError("CTP bundle proof environment does not match preflight")
        if proof.get("preflight_sha256") != snapshot.get("snapshot_sha256"):
            raise BtApiStoreError("CTP bundle proof preflight hash does not match evidence")
        return scope

    @classmethod
    def _validate_ctp_bundle_arm_projections(
        cls,
        *,
        proof: Mapping[str, Any],
        grant: Mapping[str, Any],
        preflight_scope: Mapping[str, Any],
        current_session: Mapping[str, Any],
        summary: Mapping[str, Any],
        proof_sha256: str,
    ) -> None:
        """Cross-check every public post-arm identity projection.

        The SDK exposes the same gate through a session-state projection and,
        in some versions, through execution-summary aliases.  One correct
        projection must never hide a contradictory value in another.  Missing
        optional aliases remain compatible, but at least one post-arm public
        projection must carry the complete scope version and leg list.
        """
        expected = {
            "account_fingerprint": cls._normalized_account_fingerprint(
                proof.get("account_fingerprint")
            ),
            "trading_day": proof.get("trading_day"),
            "connection_generation": proof.get("connection_generation"),
            "environment_profile": proof.get("environment_profile"),
            "instrument": proof.get("instrument"),
            "scope_version": proof.get("scope_version"),
            "authorized_instruments": list(proof.get("authorized_instruments") or ()),
            "proof_sha256": proof_sha256,
            "armed": True,
            "managed": True,
        }
        aliases = {
            "account_fingerprint": (
                "account_fingerprint",
                "execution_gate_account_fingerprint",
            ),
            "trading_day": ("trading_day", "execution_gate_trading_day"),
            "connection_generation": (
                "connection_generation",
                "execution_gate_connection_generation",
            ),
            "environment_profile": (
                "environment_profile",
                "execution_gate_environment_profile",
            ),
            "instrument": (
                "instrument",
                "execution_gate_instrument",
                "primary_instrument",
                "execution_gate_primary_instrument",
            ),
            "scope_version": ("scope_version", "execution_gate_scope_version"),
            "authorized_instruments": (
                "authorized_instruments",
                "execution_gate_authorized_instruments",
            ),
            "proof_sha256": (
                "proof_sha256",
                "arm_proof_sha256",
                "execution_gate_proof_sha256",
            ),
            "armed": ("armed", "execution_gate_armed"),
            "managed": ("managed", "execution_gate_managed"),
        }

        def _value(key: str, raw: Any) -> Any:
            if raw is None:
                raise BtApiStoreError(f"CTP bundle post-arm {key} is missing")
            if key == "account_fingerprint":
                normalized = cls._normalized_account_fingerprint(raw)
                if not normalized:
                    raise BtApiStoreError("CTP bundle post-arm account identity is invalid")
                return normalized
            if key == "authorized_instruments":
                if not isinstance(raw, (list, tuple)):
                    raise BtApiStoreError(
                        "CTP bundle post-arm authorized instrument scope is invalid"
                    )
                return list(raw)
            if key == "connection_generation":
                if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                    raise BtApiStoreError("CTP bundle post-arm generation identity is invalid")
                return raw
            if key == "proof_sha256":
                if not cls._is_sha256_hex(raw):
                    raise BtApiStoreError("CTP bundle post-arm proof identity is invalid")
                return str(raw)
            if key in {"armed", "managed"}:
                if not isinstance(raw, bool):
                    raise BtApiStoreError(f"CTP bundle post-arm {key} state is invalid")
                return raw
            if not isinstance(raw, str) or not raw.strip():
                raise BtApiStoreError(f"CTP bundle post-arm {key} identity is invalid")
            return raw

        sources = (
            ("preflight", preflight_scope),
            ("proof", proof),
            ("grant", grant),
            ("post_session", current_session),
            ("post_summary", summary),
        )
        observed: Dict[str, List[Tuple[str, str, Any]]] = collections.defaultdict(list)
        for source_name, source in sources:
            if not isinstance(source, Mapping):
                continue
            for key, names in aliases.items():
                for name in names:
                    if name in source:
                        observed[key].append((source_name, name, _value(key, source[name])))

        for key, values in observed.items():
            expected_value = expected[key]
            for source_name, alias_name, actual in values:
                if actual != expected_value:
                    raise BtApiStoreError(
                        "CTP bundle post-arm identity mismatch: "
                        f"{source_name}.{alias_name} ({key})"
                    )

        post_observed = {
            key
            for key, values in observed.items()
            if any(source_name.startswith("post_") for source_name, _name, _value in values)
        }
        required_post_identity = {
            "account_fingerprint",
            "trading_day",
            "connection_generation",
            "environment_profile",
            "instrument",
            "scope_version",
            "authorized_instruments",
        }
        if not required_post_identity.issubset(post_observed):
            raise BtApiStoreError("CTP bundle post-arm public scope projection is incomplete")

    def _validate_authorization_snapshots(self, grant: Mapping[str, Any]) -> None:
        is_bundle = set(grant) == _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS
        bundle_scope = None
        if is_bundle:
            # The V2 bundle snapshot is the authoritative scope proof.  Keep
            # the existing independent Stage A/B evidence requirement as the
            # account-level safety sweep; it does not replace the per-leg
            # bundle query and it cannot broaden the signed scope.
            bundle_scope = self._validate_bundle_scope_against_snapshot(
                grant, self._last_ctp_bundle_preflight_snapshot or {}
            )
        if len(self._ctp_preflight_history) != 2:
            raise BtApiStoreError("CTP execution authorization requires fresh Stage A/B evidence")
        stage_a, stage_b = tuple(self._ctp_preflight_history)
        if is_bundle:
            self._validate_ctp_snapshot_clock(stage_a, label="stage_a")
            self._validate_ctp_snapshot_clock(stage_b, label="stage_b")
            self._validate_ctp_snapshot_clock(
                self._last_ctp_bundle_preflight_snapshot or {}, label="bundle_preflight"
            )
        if stage_a.get("instrument_id") not in (None, ""):
            raise BtApiStoreError("CTP execution authorization Stage A scope is invalid")
        if stage_a.get("read_only_safe") is not True or stage_b.get("read_only_safe") is not True:
            raise BtApiStoreError("CTP execution authorization preflight was not read-only")
        stage_a_ids = self._snapshot_query_ids(stage_a, _CTP_STAGE_A_QUERY_NAMES)
        stage_b_ids = self._snapshot_query_ids(stage_b, _CTP_STAGE_B_QUERY_NAMES)
        if stage_a_ids is None or stage_b_ids is None:
            raise BtApiStoreError("CTP execution authorization query evidence is incomplete")
        supplied_a_ids = self._authorization_query_ids(
            grant.get("stage_a_query_request_ids"),
            _CTP_STAGE_A_QUERY_NAMES,
            "stage_a_query_request_ids",
        )
        supplied_b_ids = self._authorization_query_ids(
            grant.get("stage_b_query_request_ids"),
            _CTP_STAGE_B_QUERY_NAMES,
            "stage_b_query_request_ids",
        )
        if supplied_a_ids != stage_a_ids or supplied_b_ids != stage_b_ids:
            raise BtApiStoreError(
                "CTP execution authorization query IDs do not match Store evidence"
            )
        if set(stage_a_ids.values()).intersection(stage_b_ids.values()):
            raise BtApiStoreError("CTP execution authorization query IDs are not independent")
        if grant.get("stage_a_snapshot_sha256") != stage_a.get("snapshot_sha256"):
            raise BtApiStoreError("CTP execution authorization Stage A hash mismatch")
        if grant.get("stage_b_snapshot_sha256") != stage_b.get("snapshot_sha256"):
            raise BtApiStoreError("CTP execution authorization Stage B hash mismatch")

        account_a = self._normalized_account_fingerprint(stage_a.get("account_fingerprint"))
        account_b = self._normalized_account_fingerprint(stage_b.get("account_fingerprint"))
        scope_b = (
            self._canonical_ctp_bundle_instrument(
                stage_b.get("instrument_id"), stage_b.get("exchange_id")
            )
            if is_bundle
            else _canonical_ctp_scope(stage_b.get("instrument_id"), stage_b.get("exchange_id"))
        )
        expected = {
            "account_fingerprint": account_b,
            "trading_day": stage_b.get("trading_day"),
            "connection_generation": stage_b.get("connection_generation"),
        }
        if not is_bundle:
            expected["instrument"] = scope_b
        else:
            expected["instrument"] = bundle_scope["instrument"]
            # The V1 single-leg preflight canonicalizes symbols to upper case
            # before querying.  Bundle evidence deliberately preserves the
            # native raw InstrumentID spelling (DCE option IDs are commonly
            # lower-case), so the independent Stage-B binding is compared
            # case-insensitively while the signed V2 scope remains exact.
            if not scope_b or scope_b.casefold() != bundle_scope["instrument"].casefold():
                raise BtApiStoreError(
                    "CTP execution authorization Stage B scope is not the bundle primary"
                )
        observed = {field: grant.get(field) for field in expected}
        if expected != observed:
            raise BtApiStoreError("CTP execution authorization does not match Stage B identity")
        if (
            account_a != account_b
            or stage_a.get("trading_day") != stage_b.get("trading_day")
            or stage_a.get("connection_generation") != stage_b.get("connection_generation")
        ):
            raise BtApiStoreError("CTP execution authorization Stage A/B identity changed")
        session = stage_b.get("session_after") or stage_b.get("session") or {}
        if not isinstance(session, Mapping) or (
            grant.get("environment_profile") != session.get("environment_profile")
        ):
            raise BtApiStoreError("CTP execution authorization environment profile mismatch")

    @staticmethod
    def _recovery_position(value: Any, field_name: str) -> Dict[str, int]:
        if not isinstance(value, Mapping) or set(value) != _CTP_RECOVERY_POSITION_FIELDS:
            raise BtApiStoreError(f"CTP execution recovery {field_name} has an invalid shape")
        result = {}
        for name in sorted(_CTP_RECOVERY_POSITION_FIELDS):
            raw = value.get(name)
            if not isinstance(raw, str) or re.fullmatch(r"0|[1-9][0-9]*", raw) is None:
                raise BtApiStoreError(
                    f"CTP execution recovery {field_name}.{name} is not a canonical lot string"
                )
            result[name] = int(raw)
        return result

    @classmethod
    def _validate_execution_recovery_report(
        cls,
        report: Any,
        *,
        proof: Mapping[str, Any],
        strategy_id: str,
    ) -> Dict[str, Any]:
        report_fields = set(report) if isinstance(report, Mapping) else set()
        is_bundle = report_fields == _CTP_EXECUTION_RECOVERY_BUNDLE_FIELDS
        if report_fields not in {
            _CTP_EXECUTION_RECOVERY_FIELDS,
            _CTP_EXECUTION_RECOVERY_BUNDLE_FIELDS,
        }:
            raise BtApiStoreError("SDK execution recovery report has an invalid shape")
        result = deepcopy(dict(report))
        if is_bundle:
            if set(proof) != _CTP_EXECUTION_ARM_BUNDLE_FIELDS:
                raise BtApiStoreError("SDK execution recovery bundle proof is invalid")
            if result.get("scope_version") != _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION:
                raise BtApiStoreError("SDK execution recovery bundle scope_version is invalid")
            authorized = result.get("authorized_instruments")
            canonical_authorized = (
                [cls._canonical_ctp_bundle_instrument(item) for item in authorized]
                if isinstance(authorized, (list, tuple))
                else []
            )
            if (
                not 2 <= len(canonical_authorized) <= 3
                or canonical_authorized != list(authorized)
                or canonical_authorized != sorted(canonical_authorized)
                or len(set(canonical_authorized)) != len(canonical_authorized)
                or proof.get("scope_version") != result.get("scope_version")
                or list(proof.get("authorized_instruments") or ()) != canonical_authorized
                or proof.get("instrument") not in canonical_authorized
            ):
                raise BtApiStoreError("SDK execution recovery bundle authorized scope is invalid")
            result["authorized_instruments"] = canonical_authorized
        if result.get("schema_version") != "bt_api.execution-recovery.v1":
            raise BtApiStoreError("SDK execution recovery schema_version is invalid")
        status = result.get("status")
        if status not in {"FLAT", "RECOVERABLE", "MANUAL_INTERVENTION"}:
            raise BtApiStoreError("SDK execution recovery status is invalid")
        if any(
            not isinstance(result.get(name), bool)
            for name in ("recovery_required", "can_arm_execution", "can_arm_recovery")
        ):
            raise BtApiStoreError("SDK execution recovery admission flags are invalid")
        expected_account = cls._normalized_account_fingerprint(proof.get("account_fingerprint"))
        observed_account = cls._normalized_account_fingerprint(result.get("account_fingerprint"))
        if not expected_account or observed_account != expected_account:
            raise BtApiStoreError("SDK execution recovery account_fingerprint mismatch")
        if result.get("trading_day") != proof.get("trading_day"):
            raise BtApiStoreError("SDK execution recovery trading_day mismatch")
        if result.get("instrument") != proof.get("instrument"):
            raise BtApiStoreError("SDK execution recovery instrument mismatch")
        if result.get("connection_generation") != proof.get("connection_generation"):
            raise BtApiStoreError("SDK execution recovery connection_generation mismatch")
        if not strategy_id or result.get("strategy_id") != strategy_id:
            raise BtApiStoreError("SDK execution recovery strategy_id mismatch")
        fencing_epoch = result.get("fencing_epoch")
        if type(fencing_epoch) is not int or fencing_epoch <= 0:
            raise BtApiStoreError("SDK execution recovery fencing_epoch is invalid")
        if (
            type(result.get("unknown_ids")) is not list
            or type(result.get("evidence_errors")) is not list
        ):
            raise BtApiStoreError("SDK execution recovery evidence lists are invalid")
        if any(
            not isinstance(item, str) or not item
            for name in ("unknown_ids", "evidence_errors")
            for item in result[name]
        ):
            raise BtApiStoreError("SDK execution recovery evidence identifiers are invalid")

        remote = cls._recovery_position(result.get("remote_position"), "remote_position")
        owned = cls._recovery_position(result.get("owned_position"), "owned_position")
        if any(owned[name] > remote[name] for name in _CTP_RECOVERY_POSITION_FIELDS):
            raise BtApiStoreError("SDK execution recovery owned position exceeds remote position")
        remote_by_instrument = None
        owned_by_instrument = None
        if is_bundle:
            remote_by_instrument = result.get("remote_positions_by_instrument")
            owned_by_instrument = result.get("owned_positions_by_instrument")
            expected_scope = set(result["authorized_instruments"])
            if (
                not isinstance(remote_by_instrument, Mapping)
                or not isinstance(owned_by_instrument, Mapping)
                or set(remote_by_instrument) != expected_scope
                or set(owned_by_instrument) != expected_scope
            ):
                raise BtApiStoreError("SDK execution recovery bundle position maps are invalid")
            for instrument in result["authorized_instruments"]:
                remote_leg = cls._recovery_position(
                    remote_by_instrument[instrument],
                    f"remote_positions_by_instrument[{instrument}]",
                )
                owned_leg = cls._recovery_position(
                    owned_by_instrument[instrument],
                    f"owned_positions_by_instrument[{instrument}]",
                )
                if any(
                    owned_leg[name] > remote_leg[name] for name in _CTP_RECOVERY_POSITION_FIELDS
                ):
                    raise BtApiStoreError(
                        "SDK execution recovery bundle owned position exceeds remote position"
                    )
                if instrument == result.get("instrument") and (
                    remote_leg != remote or owned_leg != owned
                ):
                    raise BtApiStoreError(
                        "SDK execution recovery primary position does not match bundle map"
                    )
            remote_totals = {
                instrument: cls._recovery_position(
                    remote_by_instrument[instrument],
                    f"remote_positions_by_instrument[{instrument}]",
                )
                for instrument in result["authorized_instruments"]
            }
            owned_totals = {
                instrument: cls._recovery_position(
                    owned_by_instrument[instrument],
                    f"owned_positions_by_instrument[{instrument}]",
                )
                for instrument in result["authorized_instruments"]
            }
        allowed_closes = result.get("allowed_closes")
        allowed_cancels = result.get("allowed_cancels")
        allowed_actions = result.get("allowed_actions")
        if (
            type(allowed_closes) is not list
            or type(allowed_cancels) is not list
            or type(allowed_actions) is not list
            or any(type(action) is not str for action in allowed_actions)
        ):
            raise BtApiStoreError("SDK execution recovery allowed actions are invalid")

        cycle_id = result.get("execution_cycle_id")
        if cycle_id not in (None, "") and (
            not isinstance(cycle_id, str) or cycle_id != cycle_id.strip() or len(cycle_id) > 128
        ):
            raise BtApiStoreError("SDK execution recovery execution_cycle_id is invalid")
        close_totals = {"long": 0, "short": 0}
        close_totals_by_instrument: Dict[str, Any] = collections.defaultdict(
            lambda: {"long": 0, "short": 0}
        )
        seen_closes = set()
        for item in allowed_closes:
            if not isinstance(item, Mapping) or set(item) != _CTP_RECOVERY_CLOSE_FIELDS:
                raise BtApiStoreError("SDK execution recovery close action has an invalid shape")
            action = dict(item)
            if action.get("execution_cycle_id") != cycle_id:
                raise BtApiStoreError("SDK execution recovery close cycle mismatch")
            if is_bundle:
                symbol = action.get("symbol")
                exchange_id = action.get("exchange_id")
                action_scope = cls._canonical_ctp_bundle_instrument(symbol, exchange_id)
                action_valid = (
                    isinstance(symbol, str)
                    and symbol == symbol.strip()
                    and "." not in symbol
                    and isinstance(exchange_id, str)
                    and exchange_id in _CTP_EXCHANGES
                    and action_scope in result["authorized_instruments"]
                )
            else:
                action_scope = _canonical_ctp_scope(action.get("symbol"), action.get("exchange_id"))
                action_valid = action_scope == result.get("instrument")
            if not action_valid:
                raise BtApiStoreError("SDK execution recovery close instrument mismatch")
            position_side = str(action.get("position_side") or "").lower()
            side = str(action.get("side") or "").lower()
            offset = str(action.get("offset") or "").lower()
            if position_side not in {"long", "short"} or side != (
                "sell" if position_side == "long" else "buy"
            ):
                raise BtApiStoreError("SDK execution recovery close direction is invalid")
            # CZCE exposes the generic close flag.  Today/yesterday inventory
            # remains part of the ownership proof, but it must not be turned
            # into SHFE/INE-specific close-today/close-yesterday instructions.
            if offset != "close":
                raise BtApiStoreError("SDK execution recovery CZCE close offset is invalid")
            quantity = action.get("quantity")
            if (
                not isinstance(quantity, str)
                or re.fullmatch(r"[1-9][0-9]*", quantity) is None
                or action.get("quantity_unit") != "contracts"
            ):
                raise BtApiStoreError("SDK execution recovery close quantity is invalid")
            action_identity = json.dumps(
                action, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if action_identity in seen_closes:
                raise BtApiStoreError("SDK execution recovery close action is duplicated")
            seen_closes.add(action_identity)
            quantity_int = int(quantity)
            close_totals[position_side] += quantity_int
            if is_bundle:
                close_totals_by_instrument[action_scope][position_side] += quantity_int

        if is_bundle and close_totals_by_instrument:
            owned_by_scope = {
                instrument: {
                    "long": position["long_today"] + position["long_yesterday"],
                    "short": position["short_today"] + position["short_yesterday"],
                }
                for instrument, position in owned_totals.items()
            }
            remote_by_scope = {
                instrument: {
                    "long": position["long_today"] + position["long_yesterday"],
                    "short": position["short_today"] + position["short_yesterday"],
                }
                for instrument, position in remote_totals.items()
            }
            for instrument, totals in close_totals_by_instrument.items():
                if any(
                    totals[side] > owned_by_scope[instrument][side]
                    or totals[side] > remote_by_scope[instrument][side]
                    for side in totals
                ):
                    raise BtApiStoreError(
                        "SDK execution recovery bundle close exceeds owned position"
                    )

        seen_cancels = set()
        for item in allowed_cancels:
            if not isinstance(item, Mapping) or set(item) != _CTP_RECOVERY_CANCEL_FIELDS:
                raise BtApiStoreError("SDK execution recovery cancel action has an invalid shape")
            action = dict(item)
            if action.get("execution_cycle_id") != cycle_id:
                raise BtApiStoreError("SDK execution recovery cancel cycle mismatch")
            if is_bundle:
                symbol = action.get("symbol")
                exchange_id = action.get("exchange_id")
                action_scope = cls._canonical_ctp_bundle_instrument(symbol, exchange_id)
                action_valid = (
                    isinstance(symbol, str)
                    and symbol == symbol.strip()
                    and "." not in symbol
                    and isinstance(exchange_id, str)
                    and exchange_id in _CTP_EXCHANGES
                    and action_scope in result["authorized_instruments"]
                )
            else:
                action_scope = _canonical_ctp_scope(action.get("symbol"), action.get("exchange_id"))
                action_valid = action_scope == result.get("instrument")
            if not action_valid:
                raise BtApiStoreError("SDK execution recovery cancel instrument mismatch")
            identifiers = tuple(
                action.get(name) for name in ("client_order_id", "order_id", "order_ref")
            )
            if not any(value not in (None, "") for value in identifiers):
                raise BtApiStoreError("SDK execution recovery cancel identity is incomplete")
            for name in ("client_order_id", "order_id", "order_ref", "front_id", "session_id"):
                value = action.get(name)
                if isinstance(value, (Mapping, list, tuple, set, bool)):
                    raise BtApiStoreError("SDK execution recovery cancel identity is invalid")
            action_identity = json.dumps(
                action, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if action_identity in seen_cancels:
                raise BtApiStoreError("SDK execution recovery cancel action is duplicated")
            seen_cancels.add(action_identity)

        if is_bundle:
            remote_total = sum(sum(position.values()) for position in remote_totals.values())
            owned_total = sum(sum(position.values()) for position in owned_totals.values())
            owned_sides = {
                "long": sum(
                    position["long_today"] + position["long_yesterday"]
                    for position in owned_totals.values()
                ),
                "short": sum(
                    position["short_today"] + position["short_yesterday"]
                    for position in owned_totals.values()
                ),
            }
            positions_equal = all(
                owned_totals[instrument] == remote_totals[instrument]
                for instrument in result["authorized_instruments"]
            )
        else:
            remote_total = sum(remote.values())
            owned_total = sum(owned.values())
            owned_sides = {
                "long": owned["long_today"] + owned["long_yesterday"],
                "short": owned["short_today"] + owned["short_yesterday"],
            }
            positions_equal = owned == remote
        token = result.get("recovery_token_sha256")
        journal = result.get("journal_sha256")
        if status == "FLAT":
            token = str(result.get("recovery_token_sha256") or "")
            journal = str(result.get("journal_sha256") or "")
            if not (
                result["recovery_required"] is False
                and result["can_arm_execution"] is True
                and result["can_arm_recovery"] is False
                and cycle_id is None
                and remote_total == 0
                and owned_total == 0
                and not allowed_closes
                and not allowed_cancels
                and allowed_actions == ["complete"]
                and cls._is_sha256_hex(token)
                and cls._is_sha256_hex(journal)
                and not result["unknown_ids"]
                and not result["evidence_errors"]
            ):
                raise BtApiStoreError("SDK execution recovery FLAT evidence is contradictory")
        elif status == "RECOVERABLE":
            token = str(result.get("recovery_token_sha256") or "")
            journal = str(result.get("journal_sha256") or "")
            if not (
                result["recovery_required"] is True
                and result["can_arm_execution"] is False
                and result["can_arm_recovery"] is True
                and positions_equal
                and (owned_total > 0 or bool(allowed_cancels))
                and isinstance(cycle_id, str)
                and bool(cycle_id)
                and cls._is_sha256_hex(token)
                and cls._is_sha256_hex(journal)
                and not result["unknown_ids"]
                and not result["evidence_errors"]
                and not (allowed_closes and allowed_cancels)
                and bool(allowed_closes or allowed_cancels)
                and allowed_actions == (["cancel"] if allowed_cancels else ["close"])
            ):
                raise BtApiStoreError(
                    "SDK execution recovery RECOVERABLE evidence is contradictory"
                )
            if allowed_closes and close_totals != owned_sides:
                raise BtApiStoreError("SDK execution recovery closes do not cover owned position")
            if is_bundle and allowed_closes:
                expected_by_instrument = {
                    instrument: {
                        "long": position["long_today"] + position["long_yesterday"],
                        "short": position["short_today"] + position["short_yesterday"],
                    }
                    for instrument, position in owned_totals.items()
                    if position["long_today"]
                    + position["long_yesterday"]
                    + position["short_today"]
                    + position["short_yesterday"]
                    > 0
                }
                if {
                    instrument: dict(totals)
                    for instrument, totals in close_totals_by_instrument.items()
                } != expected_by_instrument:
                    raise BtApiStoreError(
                        "SDK execution recovery bundle closes do not cover each leg"
                    )
            if allowed_cancels and allowed_closes:
                raise BtApiStoreError(
                    "SDK execution recovery cannot close before cancel completion"
                )
        else:
            journal = result.get("journal_sha256")
            if not (
                result["recovery_required"] is True
                and result["can_arm_execution"] is False
                and result["can_arm_recovery"] is False
                and cycle_id is None
                and not allowed_closes
                and not allowed_cancels
                and not allowed_actions
                and result.get("recovery_token_sha256") is None
                and type(result["evidence_errors"]) is list
                and bool(result["evidence_errors"])
                and len(result["evidence_errors"]) == len(set(result["evidence_errors"]))
                and (journal is None or cls._is_sha256_hex(journal))
            ):
                raise BtApiStoreError(
                    "SDK execution recovery MANUAL_INTERVENTION evidence is contradictory"
                )
        return result

    def _validate_recovery_proof(self, proof: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
        if str(self.provider or "").strip().lower() != "btapi":
            raise BtApiStoreError("SDK execution recovery requires provider='btapi'")
        normalized, is_bundle = self._normalise_ctp_execution_proof(proof, operation="recovery")
        try:
            proof_sha256 = self._sha256_json(normalized)
        except (TypeError, ValueError):
            raise BtApiStoreError("SDK execution recovery proof is not canonical JSON") from None
        grant = self._ctp_execution_authorization
        if not isinstance(grant, Mapping) or not self._ctp_execution_authorization_sha256:
            raise BtApiStoreError("SDK execution recovery authorization is missing")
        proof_fields = _CTP_EXECUTION_ARM_BUNDLE_FIELDS if is_bundle else _CTP_EXECUTION_ARM_FIELDS
        grant_fields = set(grant) if isinstance(grant, Mapping) else set()
        if grant_fields not in {
            _CTP_EXECUTION_AUTHORIZATION_FIELDS,
            _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS,
        } or (is_bundle != (grant_fields == _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS)):
            raise BtApiStoreError("SDK execution recovery authorization has an invalid shape")
        for field in proof_fields:
            if normalized.get(field) != grant.get(field):
                raise BtApiStoreError(
                    f"SDK execution recovery proof differs from authorization: {field}"
                )
        self._validate_authorization_snapshots(grant)
        snapshot = self._get_ctp_bundle_query_health() if is_bundle else self.get_ctp_query_health()
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("read_only_safe") is not True
        ):
            raise BtApiStoreError("Current CTP preflight evidence is incomplete or stale")
        session = snapshot.get("current_session")
        if not isinstance(session, Mapping):
            session = snapshot.get("session")
        session = session if isinstance(session, Mapping) else {}
        if is_bundle:
            bundle_scope = snapshot.get("bundle_scope")
            if not isinstance(bundle_scope, Mapping):
                raise BtApiStoreError("Current CTP bundle preflight scope is unavailable")
            expected = {
                "account_fingerprint": bundle_scope.get("account_fingerprint"),
                "trading_day": bundle_scope.get("trading_day"),
                "instrument": bundle_scope.get("instrument"),
                "connection_generation": bundle_scope.get("connection_generation"),
                "environment_profile": session.get("environment_profile"),
                "scope_version": _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION,
                "authorized_instruments": bundle_scope.get("authorized_instruments"),
            }
        else:
            expected = {
                "account_fingerprint": self._normalized_account_fingerprint(
                    snapshot.get("account_fingerprint")
                ),
                "trading_day": snapshot.get("trading_day"),
                "instrument": _canonical_ctp_scope(
                    snapshot.get("instrument_id"), snapshot.get("exchange_id")
                ),
                "connection_generation": snapshot.get("connection_generation"),
                "environment_profile": session.get("environment_profile"),
            }
        observed = {
            **normalized,
            "account_fingerprint": self._normalized_account_fingerprint(
                normalized.get("account_fingerprint")
            ),
        }
        mismatches = [name for name, value in expected.items() if observed.get(name) != value]
        if mismatches:
            raise BtApiStoreError(
                "SDK execution recovery proof does not match current preflight: "
                + ",".join(sorted(mismatches))
            )
        configured_venues = set(self._sdk_exchanges)
        configured_venues.update(str(value) for value in self._sdk_routes.values())
        public_exchange_kwargs = getattr(self._api, "exchange_kwargs", None)
        if isinstance(public_exchange_kwargs, Mapping):
            configured_venues.update(str(value) for value in public_exchange_kwargs)
        configured_venues = {value.strip() for value in configured_venues if value.strip()}
        if configured_venues != {self._ctp_sdk_exchange_name()}:
            raise BtApiStoreError("SDK execution recovery requires one sole CTP provider")
        return normalized, proof_sha256

    def configure_ctp_execution_authorization(self, grant: Mapping[str, Any]) -> Dict[str, Any]:
        """Verify and bind one signed CTP capability to fresh Store evidence."""
        with self._ctp_execution_recovery_completion_lock:
            return self._configure_ctp_execution_authorization_locked(grant)

    def _configure_ctp_execution_authorization_locked(
        self, grant: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Configure authorization while recovery completion is serialized."""
        with self._command_condition:
            self._ctp_execution_authorization = None
            self._ctp_execution_authorization_sha256 = None
            self._ctp_execution_authorization_consumed = False
            recovery_generation = self._invalidate_ctp_execution_recovery_locked()
        self._prepare_sdk_execution_authorization("execution_authorization_reconfigured")
        if str(self.provider or "").strip().lower() != "btapi":
            raise BtApiStoreError("CTP execution authorization requires provider='btapi'")
        grant_fields = set(grant) if isinstance(grant, Mapping) else set()
        is_bundle = grant_fields == _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS
        if grant_fields not in {
            _CTP_EXECUTION_AUTHORIZATION_FIELDS,
            _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS,
        }:
            raise BtApiStoreError("CTP execution authorization has an invalid shape")
        grant = deepcopy(dict(grant))
        if grant.get("schema_version") != "backtrader.ctp.execution-authorization.v1":
            raise BtApiStoreError("CTP execution authorization schema is unsupported")
        try:
            grant_sha256 = self._sha256_json(grant)
        except (TypeError, ValueError):
            raise BtApiStoreError("CTP execution authorization is not canonical JSON") from None

        if grant.get("authorization_kind") != "hmac_sha256":
            raise BtApiStoreError("CTP execution authorization kind is unsupported")
        key_id = self._ctp_execution_authorization_key_id
        approval_key = self._ctp_execution_authorization_secret
        if not key_id or len(approval_key.encode("utf-8")) < 32:
            raise BtApiStoreError("CTP execution authorization trust root is unavailable")
        if not hmac.compare_digest(str(grant.get("authorization_key_id") or ""), key_id):
            raise BtApiStoreError("CTP execution authorization key identity mismatch")
        supplied_signature = self._require_sha256(
            grant.get("signature_hmac_sha256"), "signature_hmac_sha256"
        )
        unsigned_grant = {
            key: value for key, value in grant.items() if key != "signature_hmac_sha256"
        }
        expected_signature = hmac.new(
            approval_key.encode("utf-8"),
            json.dumps(
                unsigned_grant,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise BtApiStoreError("CTP execution authorization HMAC is invalid")

        issued = self._authorization_utc(grant.get("issued_at_utc"), "issued_at_utc")
        expires = self._authorization_utc(grant.get("expires_at_utc"), "expires_at_utc")
        now = _dt.datetime.now(_UTC)
        if issued > now or expires <= now or issued >= expires:
            raise BtApiStoreError("CTP execution authorization validity interval is invalid")

        hashes = (
            "stage_a_snapshot_sha256",
            "stage_b_snapshot_sha256",
            "preflight_sha256",
            "runtime_executable_sha256",
            "native_sha256",
            "ctp_package_sha256",
            "source_hashes_sha256",
            "dependency_hashes_sha256",
            "evidence_hashes_sha256",
            "receipt_sha256",
        )
        for field in hashes:
            normalized_hash = self._require_sha256(grant.get(field), field)
            if grant.get(field) != normalized_hash:
                raise BtApiStoreError(f"CTP execution authorization {field} must be lowercase")
        try:
            with open(sys.executable, "rb") as executable_file:
                runtime_sha256 = hashlib.sha256(executable_file.read()).hexdigest()
        except OSError:
            raise BtApiStoreError("CTP execution authorization runtime is unavailable") from None
        if grant["runtime_executable_sha256"] != runtime_sha256:
            raise BtApiStoreError("CTP execution authorization runtime hash mismatch")

        if grant.get("gate_statuses") != {"G1": "PASS", "G2": "PASS", "G3": "PASS"}:
            raise BtApiStoreError("CTP execution authorization gates are not PASS")
        if is_bundle:
            proof_fields = {
                field: grant[field] for field in _CTP_EXECUTION_ARM_BUNDLE_FIELDS if field in grant
            }
            self._normalise_ctp_execution_proof(proof_fields, operation="authorization")
        elif re.fullmatch(r"CZCE\.SA\d{3}", str(grant.get("instrument") or "")) is None:
            raise BtApiStoreError("CTP execution authorization instrument is invalid")
        generation = grant.get("connection_generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
            raise BtApiStoreError("CTP execution authorization connection_generation is invalid")
        if not str(grant.get("environment_profile") or "").strip():
            raise BtApiStoreError("CTP execution authorization environment_profile is invalid")
        self._validate_authorization_snapshots(grant)
        with self._command_condition:
            if recovery_generation != self._ctp_execution_recovery_generation:
                stale = True
            else:
                stale = False
                self._ctp_execution_authorization = grant
                self._ctp_execution_authorization_sha256 = grant_sha256
                self._ctp_execution_authorization_consumed = False
        if stale:
            self._force_sdk_market_data_only(
                "execution_authorization_configuration_stale",
                clear_authorization=True,
            )
            raise BtApiStoreError("CTP execution authorization configuration became stale")
        return {
            "configured": True,
            "grant_sha256": grant_sha256,
            "market_data_only": True,
        }

    def prepare_execution_recovery(self, proof: Mapping[str, Any]) -> Dict[str, Any]:
        """Ask the SDK for the sole account-bound recovery decision.

        This bridge never infers ownership from the broker's in-memory orders.
        Missing APIs, malformed evidence, and identity mismatches remain
        read-only and are surfaced as errors to the runner.
        """

        with self._ctp_execution_recovery_completion_lock:
            return self._prepare_execution_recovery_locked(proof)

    def _prepare_execution_recovery_locked(self, proof: Mapping[str, Any]) -> Dict[str, Any]:
        """Prepare a recovery plan while completion transport is serialized."""

        self._sdk_execution_config["market_data_only"] = True
        with self._command_condition:
            self._command_accept_openings = False
            recovery_generation = self._invalidate_ctp_execution_recovery_locked()
        try:
            normalized, _proof_sha256 = self._validate_recovery_proof(proof)
        except Exception:
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_rejected", clear_authorization=False
            )
            raise
        try:
            api = self._ensure_api_ready()
        except Exception:
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_api_unavailable", clear_authorization=False
            )
            raise
        prepare = getattr(api, "prepare_execution_recovery", None)
        if not callable(prepare):
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_unavailable", clear_authorization=False
            )
            raise BtApiStoreError("Public SDK execution recovery capability is unavailable")
        try:
            raw = prepare(proof=normalized)
        except Exception as exc:
            self.sanitize_exception(exc)
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_failed", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery preparation failed") from None
        try:
            result = self._validate_execution_recovery_report(
                raw,
                proof=normalized,
                strategy_id=str(self._sdk_execution_config.get("strategy_id") or ""),
            )
        except Exception:
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_invalid", clear_authorization=False
            )
            raise
        with self._command_condition:
            if recovery_generation != self._ctp_execution_recovery_generation:
                stale = True
            else:
                stale = False
                self._ctp_execution_recovery = result
                self._ctp_execution_recovery_proof = normalized
        if stale:
            self._force_sdk_market_data_only(
                "execution_recovery_prepare_stale", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery preparation became stale")
        return deepcopy(result)

    def get_execution_recovery_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the last SDK-validated immutable recovery decision."""

        if self._ctp_execution_recovery is None:
            return None
        return deepcopy(self._ctp_execution_recovery)

    def get_strategy_identity_sha256(self) -> str:
        """Return the immutable strategy identity bound into managed requests."""

        return str(self._sdk_execution_config.get("strategy_identity_sha256") or "")

    @property
    def execution_recovery_armed(self) -> bool:
        """Return whether the current SDK lease permits recovery actions only."""

        return bool(self._ctp_execution_recovery_armed)

    def abort_execution_recovery(self, reason: str) -> Dict[str, Any]:
        """Strictly revoke a recovery lease and invalidate its local proof."""

        normalized_reason = str(reason or "execution_recovery_aborted").strip()
        if (
            not normalized_reason
            or len(normalized_reason) > 128
            or not all(
                character.isalnum() or character in "._:-" for character in normalized_reason
            )
        ):
            normalized_reason = "execution_recovery_aborted"
        with self._ctp_execution_recovery_abort_lock:
            with self._command_condition:
                cached = self._ctp_execution_recovery_abort_result
                if isinstance(cached, Mapping):
                    return deepcopy(dict(cached))
                self._ctp_execution_recovery_generation += 1
                self._command_accept_openings = False
                self._sdk_execution_config["market_data_only"] = True
                self._ctp_execution_recovery_armed = False
                self._ctp_execution_recovery_proof = None
                self._ctp_execution_recovery_completion_pending = False
                self._ctp_execution_recovery_completion_receipt = None
                recovery = self._ctp_execution_recovery
                expected_generation = (
                    recovery.get("connection_generation") if isinstance(recovery, Mapping) else None
                )
            api = self._api
            disarm = getattr(api, "disarm_execution", None) if api is not None else None
            try:
                if not callable(disarm):
                    raise BtApiStoreError("Public SDK execution disarm capability is unavailable")
                raw = disarm(normalized_reason)
                observed_reason = str(raw.get("reason") or "") if isinstance(raw, Mapping) else ""
                revocation_reason = (
                    str(raw.get("revocation_reason") or "") if isinstance(raw, Mapping) else ""
                )
                reasons_valid = all(
                    value
                    and len(value) <= 128
                    and all(character.isalnum() or character in "._:-" for character in value)
                    for value in (observed_reason, revocation_reason)
                )
                valid = (
                    isinstance(raw, Mapping)
                    and set(raw)
                    == {
                        "armed",
                        "market_data_only",
                        "reason",
                        "revocation_reason",
                        "revoked_generation",
                    }
                    and raw.get("armed") is False
                    and raw.get("market_data_only") is True
                    and reasons_valid
                    and hmac.compare_digest(observed_reason, revocation_reason)
                    and type(expected_generation) is int
                    and expected_generation > 0
                    and raw.get("revoked_generation") == expected_generation
                )
                if not valid:
                    raise BtApiStoreError("SDK execution recovery abort was not proven")
            except Exception as exc:
                self.sanitize_exception(exc)
                with self._command_condition:
                    self._command_stop_requested = True
                    self._accept_command_completions = False
                    self._discard_pending_commands_locked("execution_recovery_abort_failed")
                    self._command_condition.notify_all()
                self._connected = False
                self._started = False
                self._shutdown_state = "FAIL"
                if api is not None:
                    self._bounded_sdk_close(api, self._command_shutdown_timeout)
                if isinstance(exc, BtApiStoreError):
                    raise
                raise BtApiStoreError("SDK execution recovery abort failed") from None
            result = {
                "aborted": True,
                "market_data_only": True,
                "recovery_only": False,
                "reason": observed_reason,
                "revocation_reason": revocation_reason,
                "revoked_generation": raw["revoked_generation"],
            }
            with self._command_condition:
                self._ctp_sdk_arm_attempted = False
                self._ctp_execution_recovery_abort_result = result
            return deepcopy(result)

    def arm_execution_recovery(
        self,
        proof: Mapping[str, Any],
        *,
        recovery_token_sha256: str,
    ) -> Dict[str, Any]:
        """Arm only the actions present in one SDK-issued recovery plan."""

        with self._command_condition:
            self._command_accept_openings = False
            self._sdk_execution_arming = True
        sdk_call_started = False
        try:
            normalized, proof_sha256 = self._validate_recovery_proof(proof)
            recovery = self._ctp_execution_recovery
            cached_proof = self._ctp_execution_recovery_proof
            if not isinstance(recovery, Mapping) or cached_proof != normalized:
                raise BtApiStoreError("SDK execution recovery plan is missing or stale")
            if (
                recovery.get("status") != "RECOVERABLE"
                or recovery.get("can_arm_recovery") is not True
            ):
                raise BtApiStoreError("SDK execution recovery is not armable")
            token = self._require_sha256(recovery_token_sha256, "recovery_token_sha256")
            if token != recovery.get("recovery_token_sha256"):
                raise BtApiStoreError("SDK execution recovery token mismatch")
            if self._ctp_execution_recovery_armed:
                raise BtApiStoreError("SDK execution recovery token was already armed")
            api = self._ensure_api_ready()
            arm = getattr(api, "arm_execution_recovery", None)
            if not callable(arm):
                raise BtApiStoreError("Public SDK execution recovery arming is unavailable")
            sdk_call_started = True
            self._ctp_sdk_arm_attempted = True
            raw = arm(proof=normalized, recovery_token_sha256=token)
            if not isinstance(raw, Mapping) or set(raw) != _CTP_EXECUTION_RECOVERY_ARM_FIELDS:
                raise BtApiStoreError("SDK execution recovery arming returned an invalid shape")
            result = dict(raw)
            if not (
                result.get("armed") is True
                and result.get("market_data_only") is False
                and result.get("recovery_only") is True
                and result.get("proof_sha256") == proof_sha256
                and result.get("recovery_token_sha256") == token
                and result.get("execution_cycle_id") == recovery.get("execution_cycle_id")
            ):
                raise BtApiStoreError("SDK execution recovery arming returned contradictory state")
            self._sdk_execution_config["market_data_only"] = False
            self._ctp_execution_recovery_armed = True
            return deepcopy(result)
        except Exception:
            if sdk_call_started:
                self._force_sdk_market_data_only(
                    "execution_recovery_arm_post_commit_failure",
                    clear_authorization=False,
                )
            raise
        finally:
            with self._command_condition:
                self._command_accept_openings = False
                self._sdk_execution_arming = False

    def cancel_execution_recovery_orders(self, *, recovery_token_sha256: str) -> list:
        """Queue exactly the SDK-approved cancellation set without local Order objects."""

        recovery = self._ctp_execution_recovery
        if not isinstance(recovery, Mapping) or not self._ctp_execution_recovery_armed:
            raise BtApiStoreError("SDK execution recovery is not armed")
        token = self._require_sha256(recovery_token_sha256, "recovery_token_sha256")
        if token != recovery.get("recovery_token_sha256"):
            raise BtApiStoreError("SDK execution recovery token mismatch")
        actions = list(recovery.get("allowed_cancels") or ())
        if not actions:
            return []
        with self._command_condition:
            if self._ctp_execution_recovery_cancel_requested:
                raise BtApiStoreError("SDK execution recovery cancellation was already requested")
            self._ctp_execution_recovery_cancel_requested = True
        try:
            self._ensure_api_ready()
            self._require_async_sdk_commands()
            self._start_command_worker()
            venue = self._ctp_sdk_exchange_name()
            receipts = []
            for index, action in enumerate(actions):
                symbol = str(action["symbol"])
                client_order_id = action.get("client_order_id")
                order_id = action.get("order_id")
                order_ref = action.get("order_ref")
                reference = next(
                    str(value)
                    for value in (client_order_id, order_id, order_ref)
                    if value not in (None, "")
                )
                local_ref = f"recovery:{token[:12]}:{index}"
                binding = {
                    "symbol": symbol,
                    "exchange_name": venue,
                    "account_id": self._sdk_account_id(venue),
                    "client_order_id": client_order_id,
                    "bt_order_ref": local_ref,
                    "order_id": order_id,
                    "order_ref": order_ref,
                    "exchange_id": action.get("exchange_id"),
                    "front_id": action.get("front_id"),
                    "session_id": action.get("session_id"),
                }
                self._sdk_local_refs[reference] = binding
                if client_order_id not in (None, ""):
                    self._sdk_client_refs[(venue, str(client_order_id))] = binding
                if order_id not in (None, ""):
                    self._sdk_venue_refs[(venue, str(order_id))] = binding
                receipt = self.enqueue_cancel(reference, dataname=None)
                if not isinstance(receipt, Mapping) or receipt.get("queued") is not True:
                    raise BtApiStoreError("SDK execution recovery cancellation was not queued")
                receipts.append(dict(receipt))
        except Exception:
            self._force_sdk_market_data_only(
                "execution_recovery_cancel_failed", clear_authorization=False
            )
            raise
        return receipts

    def complete_execution_recovery(self, *, recovery_token_sha256: str) -> Dict[str, Any]:
        """Let the SDK prove two-round flatness and revoke the recovery lease once."""

        with self._ctp_execution_recovery_completion_lock:
            return self._complete_execution_recovery_locked(
                recovery_token_sha256=recovery_token_sha256
            )

    def _complete_queued_execution_recovery(
        self,
        *,
        recovery_token_sha256: str,
        recovery_generation: int,
    ) -> Dict[str, Any]:
        """Complete only the recovery generation claimed by one queued receipt."""
        with self._ctp_execution_recovery_completion_lock:
            return self._complete_execution_recovery_locked(
                recovery_token_sha256=recovery_token_sha256,
                expected_generation=recovery_generation,
            )

    def _complete_execution_recovery_locked(
        self,
        *,
        recovery_token_sha256: str,
        expected_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Complete recovery while holding the per-token serialization lock."""

        with self._command_condition:
            recovery = self._ctp_execution_recovery
            recovery_generation = self._ctp_execution_recovery_generation
            if expected_generation is not None and expected_generation != recovery_generation:
                raise BtApiStoreError("SDK execution recovery completion receipt is stale")
            recovery_can_complete = (
                not self._ctp_execution_recovery_completed
                and isinstance(recovery, Mapping)
                and (
                    (
                        recovery.get("status") == "RECOVERABLE"
                        and self._ctp_execution_recovery_armed
                        and recovery.get("allowed_actions") == ["close"]
                    )
                    or (
                        recovery.get("status") == "FLAT"
                        and not self._ctp_execution_recovery_armed
                        and recovery.get("allowed_actions") == ["complete"]
                    )
                )
            )
            if not recovery_can_complete:
                raise BtApiStoreError("SDK execution recovery is not completable")
            token = self._require_sha256(recovery_token_sha256, "recovery_token_sha256")
            if token != recovery.get("recovery_token_sha256"):
                raise BtApiStoreError("SDK execution recovery token mismatch")
        complete = getattr(self._ensure_api_ready(), "complete_execution_recovery", None)
        if not callable(complete):
            self._force_sdk_market_data_only(
                "execution_recovery_completion_unavailable", clear_authorization=False
            )
            raise BtApiStoreError("Public SDK execution recovery completion is unavailable")
        try:
            raw = complete(recovery_token_sha256=token)
        except asyncio.CancelledError:
            self._force_sdk_market_data_only(
                "execution_recovery_completion_cancelled", clear_authorization=False
            )
            raise
        except Exception as exc:
            self.sanitize_exception(exc)
            self._force_sdk_market_data_only(
                "execution_recovery_completion_failed", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery completion failed") from None
        if not isinstance(raw, Mapping) or set(raw) != _CTP_EXECUTION_RECOVERY_COMPLETE_FIELDS:
            self._force_sdk_market_data_only(
                "execution_recovery_completion_invalid", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery completion returned an invalid shape")
        result = dict(raw)
        if not (
            result.get("completed") is True
            and result.get("armed") is False
            and result.get("market_data_only") is True
            and result.get("recovery_only") is False
            and result.get("requires_new_preflight") is True
            and result.get("recovery_token_sha256") == token
        ):
            self._force_sdk_market_data_only(
                "execution_recovery_completion_invalid", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery completion did not prove flatness")
        with self._command_condition:
            stale = (
                recovery_generation != self._ctp_execution_recovery_generation
                or self._ctp_execution_recovery is not recovery
                or token != recovery.get("recovery_token_sha256")
            )
            if not stale:
                self._sdk_execution_config["market_data_only"] = True
                self._command_accept_openings = False
                self._ctp_sdk_arm_attempted = False
                self._ctp_execution_recovery_armed = False
                self._ctp_execution_recovery_completed = True
                self._ctp_execution_authorization_consumed = True
        if stale:
            self._force_sdk_market_data_only(
                "execution_recovery_completion_stale", clear_authorization=False
            )
            raise BtApiStoreError("SDK execution recovery completion became stale")
        return deepcopy(result)

    def arm_sdk_execution(
        self, proof: Mapping[str, Any], *, authorization: Any = None
    ) -> Dict[str, Any]:
        """Consume one signed capability and atomically arm the managed SDK.

        V2 callers must provide the opaque authorization issued by the SDK's
        public authority path.  The Store validates the separately supplied
        proof and scope, then forwards that object unchanged; it never reads
        private token fields or manufactures an authorization object.  The
        legacy V1 proof-only call remains for compatibility with existing Store
        facades and fixtures.
        """
        if str(self.provider or "").strip().lower() != "btapi":
            raise BtApiStoreError("SDK execution arming requires provider='btapi'")
        with self._command_condition:
            self._command_accept_openings = False
            self._sdk_execution_arming = True
        try:
            proof, is_bundle = self._normalise_ctp_execution_proof(proof, operation="arming")
            if is_bundle and authorization is None:
                raise BtApiStoreError(
                    "SDK V2 execution arming requires caller-provided public authorization"
                )
            if (
                isinstance(self._ctp_execution_recovery, Mapping)
                and not self._ctp_execution_recovery_completed
            ):
                raise BtApiStoreError(
                    "SDK execution recovery must complete before ordinary execution arming"
                )
            try:
                expected_hash = self._sha256_json(proof)
            except (TypeError, ValueError):
                raise BtApiStoreError("SDK execution arming proof is not canonical JSON") from None

            grant = self._ctp_execution_authorization
            if not isinstance(grant, Mapping) or not self._ctp_execution_authorization_sha256:
                raise BtApiStoreError("SDK execution arming authorization is missing")
            if self._ctp_execution_authorization_consumed:
                raise BtApiStoreError("SDK execution arming authorization was already consumed")
            # An attempted arm consumes the capability even when a later check
            # fails. Retrying requires a freshly verified receipt and Stage A/B.
            self._ctp_execution_authorization_consumed = True
            expires = self._authorization_utc(grant.get("expires_at_utc"), "expires_at_utc")
            if expires <= _dt.datetime.now(_UTC):
                raise BtApiStoreError("SDK execution arming authorization expired")
            unsigned_grant = {
                key: value for key, value in grant.items() if key != "signature_hmac_sha256"
            }
            current_signature = hmac.new(
                self._ctp_execution_authorization_secret.encode("utf-8"),
                json.dumps(
                    unsigned_grant,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(
                str(grant.get("signature_hmac_sha256") or ""), current_signature
            ):
                raise BtApiStoreError("SDK execution arming authorization changed")
            try:
                with open(sys.executable, "rb") as executable_file:
                    runtime_hash = hashlib.sha256(executable_file.read()).hexdigest()
            except OSError:
                raise BtApiStoreError("SDK execution arming runtime is unavailable") from None
            if runtime_hash != grant.get("runtime_executable_sha256"):
                raise BtApiStoreError("SDK execution arming runtime changed")

            self._validate_authorization_snapshots(grant)
            grant_to_proof = {
                "account_fingerprint": grant.get("account_fingerprint"),
                "trading_day": grant.get("trading_day"),
                "instrument": grant.get("instrument"),
                "connection_generation": grant.get("connection_generation"),
                "environment_profile": grant.get("environment_profile"),
                "receipt_sha256": grant.get("receipt_sha256"),
                "native_sha256": grant.get("native_sha256"),
                "ctp_package_sha256": grant.get("ctp_package_sha256"),
                "source_hashes_sha256": grant.get("source_hashes_sha256"),
                "dependency_hashes_sha256": grant.get("dependency_hashes_sha256"),
                "preflight_sha256": grant.get("preflight_sha256"),
            }
            if is_bundle:
                grant_to_proof.update(
                    {
                        "scope_version": grant.get("scope_version"),
                        "authorized_instruments": grant.get("authorized_instruments"),
                    }
                )
            proof_mismatches = sorted(
                field for field, expected in grant_to_proof.items() if proof.get(field) != expected
            )
            if proof_mismatches:
                raise BtApiStoreError(
                    "SDK execution arming proof differs from authorization: "
                    + ",".join(proof_mismatches)
                )

            configured_venues = set(self._sdk_exchanges)
            configured_venues.update(str(value) for value in self._sdk_routes.values())
            public_exchange_kwargs = getattr(self._api, "exchange_kwargs", None)
            if isinstance(public_exchange_kwargs, Mapping):
                configured_venues.update(str(value) for value in public_exchange_kwargs)
            configured_venues = {value.strip() for value in configured_venues if value.strip()}
            ctp_venue = self._ctp_sdk_exchange_name()
            if configured_venues != {ctp_venue}:
                raise BtApiStoreError("SDK execution arming requires one sole CTP provider")

            with self._ctp_query_lock:
                api = self._ensure_api_ready()
                arm = getattr(api, "arm_execution_from_preflight", None)
                if not callable(arm):
                    raise BtApiStoreError("Public SDK execution arming capability is unavailable")
                snapshot = (
                    self._get_ctp_bundle_query_health()
                    if is_bundle
                    else self.get_ctp_query_health()
                )
                if (
                    snapshot.get("evidence_complete") is not True
                    or snapshot.get("read_only_safe") is not True
                ):
                    raise BtApiStoreError("Current CTP preflight evidence is incomplete or stale")

                current_session = snapshot.get("current_session")
                if not isinstance(current_session, Mapping):
                    current_session = snapshot.get("session")
                current_session = current_session if isinstance(current_session, Mapping) else {}
                snapshot_account = self._normalized_account_fingerprint(
                    snapshot.get("account_fingerprint")
                )
                proof_account = self._normalized_account_fingerprint(
                    proof.get("account_fingerprint")
                )
                if is_bundle:
                    bundle_scope = snapshot.get("bundle_scope")
                    if not isinstance(bundle_scope, Mapping):
                        raise BtApiStoreError("Current CTP bundle preflight scope is unavailable")
                    expected = {
                        "account_fingerprint": bundle_scope.get("account_fingerprint"),
                        "trading_day": bundle_scope.get("trading_day"),
                        "instrument": bundle_scope.get("instrument"),
                        "connection_generation": bundle_scope.get("connection_generation"),
                        "environment_profile": current_session.get("environment_profile"),
                        "scope_version": _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION,
                        "authorized_instruments": bundle_scope.get("authorized_instruments"),
                    }
                else:
                    expected = {
                        "account_fingerprint": snapshot_account,
                        "trading_day": snapshot.get("trading_day"),
                        "instrument": _canonical_ctp_scope(
                            snapshot.get("instrument_id"), snapshot.get("exchange_id")
                        ),
                        "connection_generation": snapshot.get("connection_generation"),
                        "environment_profile": current_session.get("environment_profile"),
                    }
                observed = {
                    "account_fingerprint": proof_account,
                    "trading_day": proof.get("trading_day"),
                    "instrument": proof.get("instrument"),
                    "connection_generation": proof.get("connection_generation"),
                    "environment_profile": proof.get("environment_profile"),
                }
                if is_bundle:
                    observed.update(
                        {
                            "scope_version": proof.get("scope_version"),
                            "authorized_instruments": proof.get("authorized_instruments"),
                        }
                    )
                mismatches = [
                    field for field, value in expected.items() if observed[field] != value
                ]
                if mismatches:
                    raise BtApiStoreError(
                        "SDK execution arming proof does not match current preflight: "
                        + ",".join(sorted(mismatches))
                    )
                try:
                    self._ctp_sdk_arm_attempted = True
                    # The current SDK public method accepts one opaque
                    # core-issued authorization object.  A redeemed
                    # ``CtpExecutionApprovalCapability`` goes through the
                    # SDK's own entry-approval arm; other opaque objects use
                    # the preflight arm, and the V1 mapping call remains a
                    # compatibility path for older Store facades.  V2 never
                    # falls back to a proof mapping.
                    approval_arm = getattr(self._api, "arm_execution_from_approval", None)
                    if _is_ctp_approval_capability(authorization):
                        if not callable(approval_arm):
                            raise BtApiStoreError("Public SDK entry approval arming is unavailable")
                        result = approval_arm(authorization)
                    else:
                        result = (
                            arm(authorization) if authorization is not None else arm(proof=proof)
                        )
                    if not isinstance(result, Mapping) or not (
                        result.get("armed") is True
                        and result.get("market_data_only") is False
                        and result.get("proof_sha256") == expected_hash
                    ):
                        raise BtApiStoreError("SDK execution arming returned an invalid result")
                    post_health = (
                        self._get_ctp_bundle_query_health()
                        if is_bundle
                        else self.get_ctp_query_health()
                    )
                    post_scope = post_health.get("bundle_scope") if is_bundle else None
                    if (
                        post_health.get("evidence_complete") is not True
                        or post_health.get("read_only_safe") is not True
                        or self._normalized_account_fingerprint(
                            post_health.get("account_fingerprint")
                        )
                        != proof_account
                        or post_health.get("trading_day") != proof.get("trading_day")
                        or post_health.get("connection_generation")
                        != proof.get("connection_generation")
                        or (
                            is_bundle
                            and (
                                not isinstance(post_scope, Mapping)
                                or post_scope.get("instrument") != proof.get("instrument")
                                or post_scope.get("authorized_instruments")
                                != proof.get("authorized_instruments")
                            )
                        )
                    ):
                        raise BtApiStoreError(
                            "SDK execution arming post-commit session check failed"
                        )
                    summary_getter = getattr(api, "get_execution_summary", None)
                    summary = summary_getter() if callable(summary_getter) else None
                    if not isinstance(summary, Mapping) or not (
                        summary.get("armed") is True
                        and summary.get("market_data_only") is False
                        and summary.get("arm_revoked") is False
                        and summary.get("arm_proof_sha256") == expected_hash
                    ):
                        raise BtApiStoreError(
                            "SDK execution arming summary did not confirm the lease"
                        )
                    if is_bundle:
                        gate_session = post_health.get("current_session")
                        if not isinstance(gate_session, Mapping):
                            gate_session = {}
                        self._validate_ctp_bundle_arm_projections(
                            proof=proof,
                            grant=grant,
                            preflight_scope=post_scope or {},
                            current_session=gate_session,
                            summary=summary,
                            proof_sha256=expected_hash,
                        )
                except Exception:
                    self._force_sdk_market_data_only(
                        "execution_arm_post_commit_failure", clear_authorization=False
                    )
                    raise
                self._sdk_execution_config["market_data_only"] = False
                return dict(result)
        finally:
            # SDK arming never bypasses the Broker-side account-risk gate.
            with self._command_condition:
                self._command_accept_openings = False
                self._sdk_execution_arming = False

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

        if self._sdk_mode:
            return self.get_symbol_info(str(dataname))
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

    def get_instrument_spec(self, dataname: str):
        """Return typed SDK instrument rules as a Backtrader-compatible mapping."""
        api = self._ensure_api_ready()
        if self._sdk_mode and callable(getattr(api, "get_instrument_spec", None)):
            metadata = _contract_mapping(
                api.get_instrument_spec(self._sdk_exchange(dataname), dataname),
                "InstrumentSpec",
            )
            contract_value = metadata.get("contract_value")
            contract_multiplier = metadata.get("contract_multiplier")
            if contract_value is not None and contract_multiplier is not None:
                metadata.setdefault(
                    "multiplier",
                    Decimal(str(contract_value)) * Decimal(str(contract_multiplier)),
                )
            metadata.setdefault("tick_size", metadata.get("price_tick"))
            metadata.setdefault("lot_size", metadata.get("quantity_step"))
            metadata.setdefault("min_size", metadata.get("min_quantity"))
            metadata.setdefault("settlement_currency", metadata.get("quote_currency"))
        elif self._sdk_mode:
            metadata = _contract_mapping(
                api.get_exchange_info(self._sdk_exchange(dataname), dataname, normalized=True),
                "instrument metadata",
            )
        elif callable(getattr(api, "get_instrument_spec", None)):
            metadata = _contract_mapping(api.get_instrument_spec(dataname), "InstrumentSpec")
        elif hasattr(api, "get_symbol_info"):
            metadata = _contract_mapping(api.get_symbol_info(dataname), "instrument metadata")
        else:
            return self.get_contract_metadata(dataname)
        self.contract_metadata[str(dataname)] = deepcopy(metadata)
        return deepcopy(metadata)

    def get_typed_instrument_spec(self, dataname: str):
        """Return the public SDK ``InstrumentSpec`` without compatibility aliases.

        Strategy runners that need cross-venue sizing use this method so they
        do not rebuild contract semantics from Backtrader's legacy mapping.
        """

        api = self._ensure_api_ready()
        if not self._sdk_mode or not callable(getattr(api, "get_instrument_spec", None)):
            raise BtApiStoreError("The configured provider has no typed InstrumentSpec contract")
        return api.get_instrument_spec(self._sdk_exchange(dataname), dataname)

    def get_symbol_info(self, dataname: str):
        """Compatibility alias for :meth:`get_instrument_spec`."""
        return self.get_instrument_spec(dataname)

    def _funding_cache_key(self, dataname: str) -> Tuple[str, str]:
        """Return the route-qualified identity used by the funding cache."""
        symbol = str(dataname)
        if self._sdk_mode:
            route = self._sdk_exchange(symbol)
        else:
            route = self._sdk_routes.get(symbol, self.provider)
        return str(route), symbol

    def _read_funding_snapshot_from_api(self, api: Any, dataname: str) -> Dict[str, Any]:
        """Perform exactly one SDK/provider funding read without cache policy."""
        if self._sdk_mode and callable(getattr(api, "get_funding_snapshot", None)):
            return _contract_mapping(
                api.get_funding_snapshot(self._sdk_exchange(dataname), dataname),
                "FundingSnapshot",
            )
        if self._sdk_mode and callable(getattr(api, "get_funding_rate", None)):
            return _contract_mapping(
                api.get_funding_rate(self._sdk_exchange(dataname), dataname, normalized=True),
                "funding snapshot",
            )
        if callable(getattr(api, "get_funding_snapshot", None)):
            return _contract_mapping(api.get_funding_snapshot(dataname), "FundingSnapshot")
        if callable(getattr(api, "get_funding_rate", None)):
            return _contract_mapping(api.get_funding_rate(dataname), "funding snapshot")
        raise BtApiStoreError("The provider does not expose funding rates")

    def _read_funding_snapshot(self, dataname: str) -> Dict[str, Any]:
        """Read funding through the serialized metadata transport boundary."""
        if self._funding_restart_blocked_by_worker:
            self._prepare_funding_refresh_start()
        with self._funding_condition:
            if self._funding_stop_requested and (self._started or self._connected):
                raise BtApiStoreError("The Store is stopping; funding reads are unavailable")
            self._funding_direct_inflight += 1
        try:
            api = self._ensure_api_ready()
            with self._funding_transport_lock:
                return self._read_funding_snapshot_from_api(api, dataname)
        finally:
            with self._funding_condition:
                self._funding_direct_inflight -= 1
                self._funding_condition.notify_all()

    @staticmethod
    def _funding_compat_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        """Preserve the historical synchronous API's Unix timestamp shape."""
        snapshot = deepcopy(dict(snapshot))
        next_funding_time = snapshot.get("next_funding_time")
        if isinstance(next_funding_time, _dt.datetime):
            if next_funding_time.tzinfo is None:
                next_funding_time = next_funding_time.replace(tzinfo=_dt.timezone.utc)
            snapshot["next_funding_time"] = next_funding_time.timestamp()
        return snapshot

    def _canonical_funding_snapshot(
        self, snapshot: Mapping[str, Any], key: Tuple[str, str]
    ) -> Dict[str, Any]:
        """Deep-copy the public contract and normalize its nested freshness mapping."""
        result = deepcopy(dict(snapshot))
        freshness = result.get("freshness")
        if is_dataclass(freshness) and not isinstance(freshness, type):
            freshness = asdict(freshness)
        elif isinstance(freshness, Mapping):
            freshness = deepcopy(dict(freshness))
        if freshness is not None:
            result["freshness"] = freshness
        # SDK metadata is an identity-bound public contract.  Filling missing
        # fields here would make a malformed response appear to belong to the
        # requested route.  Legacy non-SDK providers retain their compatibility
        # defaults, while SDK responses must prove their own identity below.
        if not self._sdk_mode:
            result.setdefault("exchange_name", key[0])
            result.setdefault("symbol", key[1])
        return result

    @staticmethod
    def _funding_snapshot_invalid_reason(
        snapshot: Mapping[str, Any],
        now_epoch: float,
        expected_key: Optional[Tuple[str, str]] = None,
        max_age_seconds: Optional[float] = None,
    ) -> str:
        """Return the fail-closed reason for a typed funding contract."""
        if expected_key is not None:
            exchange_name = snapshot.get("exchange_name")
            symbol = snapshot.get("symbol")
            if exchange_name in (None, ""):
                return "funding_exchange_name_missing"
            if str(exchange_name) != expected_key[0]:
                return "funding_exchange_name_mismatch"
            if symbol in (None, ""):
                return "funding_symbol_missing"
            if str(symbol) != expected_key[1]:
                return "funding_symbol_mismatch"
        freshness = snapshot.get("freshness")
        if snapshot.get("available") is not True:
            if isinstance(freshness, Mapping):
                reason = str(freshness.get("stale_reason") or "").strip()
                if reason:
                    return reason
            return "funding_unavailable"
        if not isinstance(freshness, Mapping):
            return "funding_freshness_missing"
        if freshness.get("stale") is not False:
            return str(freshness.get("stale_reason") or "funding_stale")
        if expected_key is not None:
            observed_at = freshness.get("observed_at")
            if observed_at in (None, ""):
                return "funding_observed_at_missing"
            if not isinstance(observed_at, _dt.datetime):
                return "funding_observed_at_invalid"
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                return "funding_observed_at_timezone_missing"
            try:
                observed_epoch = float(observed_at.timestamp())
            except (OverflowError, OSError, ValueError):
                return "funding_observed_at_invalid"
            if not math.isfinite(observed_epoch):
                return "funding_observed_at_invalid"
            if observed_epoch > now_epoch:
                return "funding_observed_at_in_future"
            if max_age_seconds is not None and now_epoch - observed_epoch >= max_age_seconds:
                return "funding_cache_ttl_expired"
        if expected_key is not None:
            try:
                _, coerce_funding_snapshot, _ = _sdk_cross_venue_contracts()
                coerce_funding_snapshot(
                    snapshot,
                    now_epoch=Decimal(str(now_epoch)),
                    expected_exchange_name=expected_key[0],
                    expected_symbol=expected_key[1],
                )
            except (BtApiStoreError, TypeError, ValueError, InvalidOperation) as exc:
                return str(exc) or "funding_snapshot_invalid"
        return ""

    @staticmethod
    def _funding_next_epoch(snapshot: Mapping[str, Any]) -> Optional[float]:
        value = snapshot.get("next_funding_time")
        try:
            if isinstance(value, _dt.datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    return None
                value = value.timestamp()
            result = float(Decimal(str(value)))
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _funding_source_age_seconds(snapshot: Mapping[str, Any], now_epoch: float) -> float:
        """Return the age of a previously validated SDK funding snapshot."""
        freshness = snapshot.get("freshness")
        if not isinstance(freshness, Mapping):
            return 0.0
        observed_at = freshness.get("observed_at")
        if not isinstance(observed_at, _dt.datetime):
            return 0.0
        return max(now_epoch - observed_at.timestamp(), 0.0)

    @staticmethod
    def _is_funding_transport_error(exc: BaseException) -> bool:
        """Recognize failures that cannot contradict a prior typed snapshot."""
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        if bool(getattr(exc, "transport_error", False)) or bool(getattr(exc, "retryable", False)):
            return True
        name = type(exc).__name__.lower()
        return any(token in name for token in ("connection", "network", "timeout", "transport"))

    @staticmethod
    def _typed_funding_transport_failure(snapshot: Mapping[str, Any]) -> bool:
        """Accept only the SDK's explicit, internally consistent transport reason."""
        freshness = snapshot.get("freshness")
        return bool(
            snapshot.get("available") is False
            and snapshot.get("unavailable_reason") == "funding_transport_failed"
            and isinstance(freshness, Mapping)
            and freshness.get("stale") is True
            and freshness.get("stale_reason") == "funding_transport_failed"
        )

    def _has_unexpired_funding_record_locked(
        self,
        key: Tuple[str, str],
        generation: int,
        now_monotonic: float,
        now_epoch: float,
    ) -> bool:
        """Return whether the current record is still a valid last-good snapshot."""
        record = self._funding_cache.get(key)
        if (
            record is None
            or int(record.get("generation", -1)) != generation
            or record.get("invalid_reason")
            or now_monotonic >= float(record.get("deadline_monotonic", 0.0))
        ):
            return False
        return not self._funding_snapshot_invalid_reason(
            record["snapshot"],
            now_epoch,
            expected_key=key if self._sdk_mode else None,
            max_age_seconds=self._funding_max_age_seconds if self._sdk_mode else None,
        )

    def _publish_funding_snapshot_locked(
        self,
        key: Tuple[str, str],
        snapshot: Mapping[str, Any],
        generation: int,
    ) -> Dict[str, Any]:
        """Publish one read atomically; caller holds ``_funding_condition``."""
        now_monotonic = time.monotonic()
        now_epoch = time.time()
        normalized = self._canonical_funding_snapshot(snapshot, key)
        invalid_reason = self._funding_snapshot_invalid_reason(
            normalized,
            now_epoch,
            expected_key=key if self._sdk_mode else None,
            max_age_seconds=self._funding_max_age_seconds if self._sdk_mode else None,
        )
        if invalid_reason == "funding_transport_failed" and self._typed_funding_transport_failure(
            normalized
        ):
            self._funding_last_errors[key] = invalid_reason
            self._funding_health["failed"] += 1
            self._funding_health["transport_errors"] += 1
            if self._has_unexpired_funding_record_locked(
                key,
                generation,
                now_monotonic,
                now_epoch,
            ):
                return normalized
        next_epoch = self._funding_next_epoch(normalized)
        source_age = (
            self._funding_source_age_seconds(normalized, now_epoch)
            if self._sdk_mode and not invalid_reason
            else 0.0
        )
        source_origin_monotonic = now_monotonic - source_age
        ttl_deadline = source_origin_monotonic + self._funding_max_age_seconds
        schedule_deadline = (
            None if next_epoch is None else now_monotonic + max(next_epoch - now_epoch, 0.0)
        )
        deadline = (
            ttl_deadline if schedule_deadline is None else min(ttl_deadline, schedule_deadline)
        )
        if invalid_reason:
            normalized["available"] = False
            freshness = normalized.get("freshness")
            if not isinstance(freshness, Mapping):
                freshness = {"source": "btapistore_cache", "observed_at": None}
            else:
                freshness = dict(freshness)
            freshness["stale"] = True
            freshness["stale_reason"] = invalid_reason
            normalized["freshness"] = freshness
            self._funding_last_errors[key] = invalid_reason
            self._funding_health["unavailable"] += 1
        else:
            self._funding_last_errors.pop(key, None)
            self._funding_health["available"] += 1
        self._funding_cache[key] = {
            "snapshot": normalized,
            "stored_monotonic": now_monotonic,
            "source_age_at_store_seconds": source_age,
            "source_origin_monotonic": source_origin_monotonic,
            "deadline_monotonic": deadline,
            "schedule_deadline_monotonic": schedule_deadline,
            "next_funding_epoch": next_epoch,
            "generation": generation,
            "invalid_reason": invalid_reason,
        }
        self._funding_health["completed"] += 1
        return normalized

    def _record_funding_refresh_error_locked(
        self, key: Tuple[str, str], exc: BaseException, generation: int
    ) -> None:
        """Retain last-good only for a pure transport failure."""
        error_code = self._safe_exception_code(exc, type(exc).__name__)
        self._funding_last_errors[key] = error_code
        self._funding_health["failed"] += 1
        if self._is_funding_transport_error(exc):
            self._funding_health["transport_errors"] += 1
            return
        self._funding_health["contract_errors"] += 1
        now = _dt.datetime.now(_dt.timezone.utc)
        unavailable = {
            "exchange_name": key[0],
            "symbol": key[1],
            "available": False,
            "source": "btapistore_cache",
            "freshness": {
                "source": "btapistore_cache",
                "observed_at": now,
                "stale": True,
                "stale_reason": "funding_refresh_failed",
            },
        }
        self._publish_funding_snapshot_locked(key, unavailable, generation)
        self._funding_last_errors[key] = error_code

    def _funding_cache_view_locked(
        self, key: Tuple[str, str], max_age_seconds: float
    ) -> Dict[str, Any]:
        """Build a local-only typed cache view while holding the funding lock."""
        now_monotonic = time.monotonic()
        now_epoch = time.time()
        record = self._funding_cache.get(key)
        pending = key in self._funding_pending
        generation = self._funding_generation
        last_error = self._funding_last_errors.get(key)
        cache_age = None
        deadline = None
        invalid_reason = "funding_cache_missing"

        if record is None:
            result = {
                "exchange_name": key[0],
                "symbol": key[1],
                "available": False,
                "source": "btapistore_cache",
                "freshness": {
                    "source": "btapistore_cache",
                    "observed_at": None,
                    "stale": True,
                    "stale_reason": invalid_reason,
                },
            }
            cache_generation = generation
        else:
            result = deepcopy(record["snapshot"])
            cache_generation = int(record["generation"])
            local_cache_age = max(now_monotonic - float(record["stored_monotonic"]), 0.0)
            source_age = max(float(record.get("source_age_at_store_seconds", 0.0)), 0.0)
            cache_age = source_age + local_cache_age
            source_origin = float(
                record.get(
                    "source_origin_monotonic",
                    float(record["stored_monotonic"]) - source_age,
                )
            )
            age_deadline = source_origin + max_age_seconds
            schedule_deadline = record.get("schedule_deadline_monotonic")
            configured_deadline = float(record.get("deadline_monotonic", age_deadline))
            deadlines = [age_deadline, configured_deadline]
            if schedule_deadline is not None:
                deadlines.append(float(schedule_deadline))
            deadline = min(deadlines)
            invalid_reason = str(record.get("invalid_reason") or "")
            if cache_generation != generation:
                invalid_reason = "funding_cache_generation_mismatch"
            elif generation > 0 and not self._funding_accept_results:
                invalid_reason = "funding_cache_generation_inactive"
            elif max_age_seconds <= 0 or cache_age >= max_age_seconds:
                invalid_reason = "funding_cache_ttl_expired"
            elif deadline is not None and now_monotonic >= deadline:
                invalid_reason = (
                    "funding_schedule_expired"
                    if schedule_deadline is not None and now_monotonic >= float(schedule_deadline)
                    else "funding_cache_ttl_expired"
                )
            else:
                next_epoch = record.get("next_funding_epoch")
                if next_epoch is not None and float(next_epoch) <= now_epoch:
                    invalid_reason = "funding_schedule_expired"
                elif not invalid_reason:
                    invalid_reason = self._funding_snapshot_invalid_reason(
                        result,
                        now_epoch,
                        expected_key=key if self._sdk_mode else None,
                        max_age_seconds=max_age_seconds if self._sdk_mode else None,
                    )

            if invalid_reason:
                result["available"] = False
                freshness = result.get("freshness")
                freshness = dict(freshness) if isinstance(freshness, Mapping) else {}
                freshness.setdefault("source", result.get("source") or "btapistore_cache")
                freshness.setdefault("observed_at", None)
                freshness["stale"] = True
                freshness["stale_reason"] = invalid_reason
                result["freshness"] = freshness

        result.update(
            cache_age_seconds=cache_age,
            cache_deadline_monotonic=deadline,
            cache_generation=cache_generation,
            funding_generation=generation,
            refresh_pending=pending,
            last_refresh_error=last_error,
        )
        return result

    def request_funding_refresh(self, dataname: str, *, force: bool = False) -> Dict[str, Any]:
        """Coalesce a non-blocking funding refresh onto the metadata-only lane."""
        key = self._funding_cache_key(dataname)
        now = time.monotonic()
        with self._funding_condition:
            if (
                not self._started
                or not self._connected
                or not self._funding_accept_results
                or self._funding_stop_requested
                or self._api is None
            ):
                return {"queued": False, "status": "store_not_running"}
            if key in self._funding_pending:
                self._funding_health["coalesced"] += 1
                return {"queued": True, "status": "already_pending"}
            last_requested = self._funding_last_requested.get(key)
            if (
                not force
                and last_requested is not None
                and now - last_requested < self._funding_refresh_interval_seconds
            ):
                self._funding_health["throttled"] += 1
                return {"queued": False, "status": "refresh_interval"}
            generation = self._funding_generation
            self._funding_last_requested[key] = now
            self._funding_pending.add(key)
            self._funding_queue.append((generation, key, str(dataname), self._api))
            self._funding_health["requested"] += 1
            self._start_funding_refresh_worker_locked()
            self._funding_condition.notify_all()
            return {
                "queued": True,
                "status": "queued",
                "exchange_name": key[0],
                "symbol": key[1],
                "generation": generation,
            }

    def enqueue_funding_refresh(self, dataname: str, *, force: bool = False) -> Dict[str, Any]:
        """Compatibility spelling for :meth:`request_funding_refresh`."""
        return self.request_funding_refresh(dataname, force=force)

    def wait_for_funding_refreshes(self, timeout: Optional[float] = None) -> bool:
        """Wait only for tests/shutdown; normal strategy reads remain non-blocking."""
        timeout = self._command_shutdown_timeout if timeout is None else max(float(timeout), 0.0)
        deadline = time.monotonic() + timeout
        with self._funding_condition:
            while (
                self._funding_queue
                or self._funding_inflight_key is not None
                or self._funding_direct_inflight
                or (
                    self._funding_stop_requested
                    and self._funding_worker_thread is not None
                    and self._funding_worker_thread.is_alive()
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._funding_condition.wait(timeout=remaining)
        return True

    def get_cached_funding_snapshot(
        self,
        dataname: str,
        *,
        max_age_seconds: Optional[float] = None,
        request_refresh: bool = True,
    ) -> Dict[str, Any]:
        """Return a pure-local funding view and optionally enqueue a refresh."""
        max_age = (
            self._funding_max_age_seconds if max_age_seconds is None else float(max_age_seconds)
        )
        if not math.isfinite(max_age) or max_age < 0:
            raise ValueError("max_age_seconds must be finite and nonnegative")
        key = self._funding_cache_key(dataname)
        with self._funding_condition:
            view = self._funding_cache_view_locked(key, max_age)
        should_refresh = bool(
            request_refresh
            and (
                view.get("available") is not True
                or view.get("cache_age_seconds") is None
                or float(view["cache_age_seconds"]) >= self._funding_refresh_interval_seconds
            )
        )
        if should_refresh:
            self.request_funding_refresh(dataname)
            with self._funding_condition:
                view = self._funding_cache_view_locked(key, max_age)
        return view

    def get_funding_refresh_health(self, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Return a self-consistent snapshot of the metadata lane and cache."""
        key = None if dataname is None else self._funding_cache_key(dataname)
        with self._funding_condition:
            entries = {}
            for entry_key, record in self._funding_cache.items():
                entries[f"{entry_key[0]}:{entry_key[1]}"] = {
                    "generation": record["generation"],
                    "stored_monotonic": record["stored_monotonic"],
                    "source_age_at_store_seconds": record.get("source_age_at_store_seconds", 0.0),
                    "deadline_monotonic": record["deadline_monotonic"],
                    "invalid_reason": record["invalid_reason"],
                    "last_refresh_error": self._funding_last_errors.get(entry_key),
                    "pending": entry_key in self._funding_pending,
                }
            last_error = self._funding_last_errors.get(key) if key is not None else None
            if key is None and self._funding_last_errors:
                last_error = next(reversed(self._funding_last_errors.values()))
            result = {
                **dict(self._funding_health),
                "generation": self._funding_generation,
                "worker_alive": bool(
                    self._funding_worker_thread and self._funding_worker_thread.is_alive()
                ),
                "queue_depth": len(self._funding_queue),
                "inflight": bool(
                    self._funding_inflight_key is not None or self._funding_direct_inflight
                ),
                "inflight_key": self._funding_inflight_key,
                "direct_inflight": self._funding_direct_inflight,
                "pending": len(self._funding_pending),
                "accepting_results": self._funding_accept_results,
                "restart_blocked_by_worker": self._funding_restart_blocked_by_worker,
                "last_refresh_error": last_error,
                "cache_entries": entries,
            }
            for counter in (
                "requested",
                "dequeued",
                "completed",
                "available",
                "unavailable",
                "failed",
                "transport_errors",
                "contract_errors",
                "coalesced",
                "throttled",
                "discarded_unsent",
                "stale_generation_results",
                "worker_stop_timeouts",
            ):
                result.setdefault(counter, 0)
            return result

    def get_funding_snapshot(self, dataname: str):
        """Synchronously read funding and preserve the historical Unix-time API."""
        key = self._funding_cache_key(dataname)
        with self._funding_condition:
            generation = self._funding_generation
        try:
            snapshot = self._read_funding_snapshot(dataname)
        except Exception as exc:
            self.sanitize_exception(exc)
            with self._funding_condition:
                if generation == self._funding_generation and (
                    self._funding_accept_results or generation == 0
                ):
                    self._record_funding_refresh_error_locked(key, exc, generation)
            raise
        published = snapshot
        with self._funding_condition:
            if generation == self._funding_generation and (
                self._funding_accept_results or generation == 0
            ):
                published = self._publish_funding_snapshot_locked(key, snapshot, generation)
        return self._funding_compat_snapshot(published)

    def get_funding_rate(self, dataname: str):
        """Compatibility alias returning the normalized funding snapshot mapping."""
        return self.get_funding_snapshot(dataname)

    def get_typed_funding_snapshot(self, dataname: str):
        """Return the public SDK ``FundingSnapshot`` without a compatibility map."""

        api = self._ensure_api_ready()
        if not self._sdk_mode or not callable(getattr(api, "get_funding_snapshot", None)):
            raise BtApiStoreError("The configured provider has no typed FundingSnapshot contract")
        return api.get_funding_snapshot(self._sdk_exchange(dataname), dataname)

    def get_fee_schedule(self, dataname: str, account_id: Optional[str] = None):
        """Return account fee rates with explicit availability and freshness."""
        api = self._ensure_api_ready()
        venue = self._sdk_exchange(dataname) if self._sdk_mode else None
        if self._sdk_mode and callable(getattr(api, "get_fee_schedule", None)):
            resolved_account_id = self._sdk_account_id(venue, account_id)
            return _contract_mapping(
                api.get_fee_schedule(venue, dataname, resolved_account_id),
                "FeeSchedule",
            )
        if callable(getattr(api, "get_fee_schedule", None)):
            return _contract_mapping(
                api.get_fee_schedule(dataname, account_id=account_id),
                "FeeSchedule",
            )
        raise BtApiStoreError("The provider does not expose a fee schedule")

    def get_typed_fee_schedule(self, dataname: str, account_id: Optional[str] = None):
        """Return the public SDK account ``FeeSchedule`` without remapping it."""

        api = self._ensure_api_ready()
        venue = self._sdk_exchange(dataname) if self._sdk_mode else None
        if not self._sdk_mode or not callable(getattr(api, "get_fee_schedule", None)):
            raise BtApiStoreError("The configured provider has no typed FeeSchedule contract")
        return api.get_fee_schedule(venue, dataname, self._sdk_account_id(venue, account_id))

    def get_account_config(self, dataname: str):
        """Return routed account mode and explicit trading permission."""
        api = self._ensure_api_ready()
        if self._sdk_mode:
            return _contract_mapping(
                api.get_account_config(self._sdk_exchange(dataname), normalized=True),
                "account configuration",
            )
        if not hasattr(api, "get_account_config"):
            raise BtApiStoreError("The provider does not expose account configuration")
        return _contract_mapping(api.get_account_config(dataname), "account configuration")

    def get_environment_info(self, dataname: str):
        """Return the public SDK's credential-free routed environment proof."""
        api = self._ensure_api_ready()
        if not self._sdk_mode or not hasattr(api, "get_environment_info"):
            raise BtApiStoreError("The provider does not expose environment information")
        return dict(api.get_environment_info(self._sdk_exchange(dataname)))

    def get_trading_readiness(
        self,
        dataname: str,
        quantity_native,
        *,
        margin_mode: str = "cross",
        expected_position_mode: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """Return the unified typed readiness contract as a compatibility mapping."""
        api = self._ensure_api_ready()
        if self._sdk_mode and callable(getattr(api, "get_trading_readiness", None)):
            venue = self._sdk_exchange(dataname)
            contract = api.get_trading_readiness(
                venue,
                dataname,
                self._sdk_account_id(venue, account_id),
                quantity_native,
                margin_mode=margin_mode,
                position_mode=expected_position_mode,
            )
            snapshot = _contract_mapping(contract, "TradingReadiness")
            snapshot["ready"] = bool(getattr(contract, "ready", snapshot.get("ready", False)))
            reasons = snapshot.get("blocked_reasons", snapshot.get("reasons", ()))
            snapshot["reasons"] = list(reasons or ())
            snapshot.setdefault(
                "definite_failure",
                bool(_DEFINITE_READINESS_REASONS.intersection(snapshot["reasons"])),
            )
            return snapshot
        if self._sdk_mode:
            snapshot = _contract_mapping(
                api.get_order_readiness(
                    self._sdk_exchange(dataname),
                    dataname,
                    quantity_native,
                    margin_mode=margin_mode,
                    position_mode=expected_position_mode,
                    normalized=True,
                ),
                "order readiness",
            )
            snapshot["reasons"] = list(snapshot.get("reasons") or ())
            return snapshot
        if callable(getattr(api, "get_trading_readiness", None)):
            contract = api.get_trading_readiness(
                dataname,
                account_id=account_id,
                quantity_native=quantity_native,
                margin_mode=margin_mode,
                position_mode=expected_position_mode,
            )
            snapshot = _contract_mapping(contract, "TradingReadiness")
            snapshot["ready"] = bool(getattr(contract, "ready", snapshot.get("ready", False)))
            snapshot["reasons"] = list(
                snapshot.get("blocked_reasons", snapshot.get("reasons", ())) or ()
            )
            return snapshot
        if not hasattr(api, "get_order_readiness"):
            raise BtApiStoreError("The provider does not expose order readiness")
        snapshot = _contract_mapping(
            api.get_order_readiness(
                dataname,
                quantity_native,
                margin_mode=margin_mode,
                position_mode=expected_position_mode,
            ),
            "order readiness",
        )
        snapshot["reasons"] = list(snapshot.get("reasons") or ())
        return snapshot

    def get_order_readiness(
        self,
        dataname: str,
        quantity_native,
        *,
        margin_mode: str = "cross",
        position_mode: Optional[str] = None,
    ):
        """Compatibility alias for :meth:`get_trading_readiness`."""
        return self.get_trading_readiness(
            dataname,
            quantity_native,
            margin_mode=margin_mode,
            expected_position_mode=position_mode,
        )

    def get_venue_balances(self, force: bool = False):
        """Return available cash and equity separately for each configured venue."""
        api = self._ensure_api_ready()
        if not force and self._is_cache_fresh(
            self._last_venue_balance_refresh, self._account_cache_ttl
        ):
            return deepcopy(self._venue_balance_cache)
        if self._sdk_mode:
            balances = api.get_all_balances(normalized=True)
        elif hasattr(api, "get_venue_balances"):
            balances = api.get_venue_balances()
        else:
            raise BtApiStoreError("The provider does not expose per-venue balances")
        self._venue_balance_cache = deepcopy(balances)
        self._last_venue_balance_refresh = time.monotonic()
        return deepcopy(balances)

    def get_venue_balance(self, dataname: str, force: bool = False):
        """Return the account snapshot for the venue routed to ``dataname``.

        The SDK owns exchange account normalization.  This thin store method
        only resolves Backtrader's feed symbol to the configured venue and
        selects that venue from the shared balance snapshot.
        """
        balances = self.get_venue_balances(force=force)
        if self._sdk_mode:
            venue = self._sdk_exchange(dataname)
        else:
            venue = self._sdk_routes.get(str(dataname), str(dataname))
            if venue not in balances and len(balances) == 1:
                venue = next(iter(balances))
        if venue not in balances:
            raise BtApiStoreError(f"No account balance is available for venue {venue!r}")
        return deepcopy(balances[venue])

    def get_cached_venue_balance(self, dataname: str):
        """Return a previously hydrated venue balance without transport I/O."""
        venue = self._sdk_exchange(dataname) if self._sdk_mode else self._sdk_routes.get(dataname)
        if venue not in self._venue_balance_cache:
            raise BtApiStoreError(f"No cached account balance is available for venue {venue!r}")
        return deepcopy(self._venue_balance_cache[venue])

    def apply_reconcile_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        """Refresh read-only caches from a worker result on the Cerebro thread."""
        venue_balances = snapshot.get("venue_balances")
        if isinstance(venue_balances, Mapping):
            self._venue_balance_cache = deepcopy(dict(venue_balances))
            self._last_venue_balance_refresh = time.monotonic()
        balance = snapshot.get("balance")
        normalized = _normalise_account_balance_payload(balance)
        if normalized is not None:
            cash, value = normalized
            if cash is not None:
                self._cash = cash
            if value is not None:
                self._value = value
            self._last_balance_refresh = time.monotonic()
        positions = snapshot.get("positions")
        if isinstance(positions, list):
            self._positions_cache = deepcopy(positions)
            self._last_positions_refresh = time.monotonic()
        open_orders = snapshot.get("open_orders")
        if isinstance(open_orders, list):
            self._open_orders_cache = deepcopy(open_orders)
            self._last_open_orders_refresh = time.monotonic()

    def get_execution_summary(self):
        """Read the active session, or its stop snapshot without reconnecting."""
        if self._last_execution_summary is not None:
            return deepcopy(self._last_execution_summary)
        api = self._ensure_api_ready()
        if not hasattr(api, "get_execution_summary"):
            raise BtApiStoreError("The provider does not expose execution audit counts")
        return deepcopy(api.get_execution_summary())

    def _cache_account_risk_snapshot_before_shutdown(self) -> None:
        """Retain an existing safe view without starting shutdown-time network I/O.

        Account-risk reads can require several authenticated venue requests.  A
        fresh read here would consume the caller's shutdown deadline before the
        SDK transports are closed.  Runtime reconciliation already publishes an
        identity-bound cache; when none exists, post-stop callers receive the
        explicit unavailable contract instead of a guessed snapshot.
        """
        if not self._sdk_owned_api or self._api is None:
            return
        with self._account_risk_lock:
            cached = (
                self._last_account_risk_snapshot is not None
                and self._last_account_risk_snapshot_generation == self._stream_generation
            )
            if not cached:
                self._last_account_risk_snapshot = None
                self._last_account_risk_snapshot_generation = None
        if cached:
            return
        try:
            snapshot = self._read_account_risk_snapshot(self._api)
        except Exception as exc:
            # Shutdown must still close a synchronous compatibility client if
            # its optional risk diagnostic violates the public contract.
            self.sanitize_exception(exc)
            return
        self._cache_account_risk_snapshot(snapshot)

    def _cache_account_risk_snapshot(self, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        """Publish one validated, redacted account-risk snapshot for callback reads."""
        safe_snapshot = cast(Dict[str, Any], self.redact_runtime_value(dict(snapshot)))
        with self._account_risk_lock:
            self._last_account_risk_snapshot = deepcopy(safe_snapshot)
            self._last_account_risk_snapshot_generation = self._stream_generation
            self._last_account_risk_refresh_requested = time.monotonic()
        return deepcopy(safe_snapshot)

    def _cached_account_risk_unavailable(self) -> Dict[str, Any]:
        routes = sorted(str(venue) for venue in self._sdk_exchanges)
        return {
            "schema_version": 1,
            "baseline_equity": None,
            "current_equity": None,
            "realized_net": None,
            "configured_venues": sorted({self._public_sdk_venue(venue) for venue in routes}),
            "configured_venue_routes": routes,
            "baseline_equity_by_venue": None,
            "current_equity_by_venue": None,
            "currency": None,
            "generation": 0,
            "fencing_epoch": 0,
            "as_of_monotonic_ns": 0,
            "owner_pid": None,
            "clock_domain_id": "",
            "identity_binding_sha256": "",
            "durable": False,
            "trading_blocked": True,
            "loss_limit_bps": self._sdk_execution_config.get("account_maximum_loss_bps"),
            "loss_limit_breached": False,
            "loss_breached_at": None,
            "loss_amount": None,
            "loss_limit_amount": None,
            "loss_bps_observed": None,
            "peak_loss_bps": None,
            "blocked_reasons": ["account_risk_cache_unavailable"],
            "evidence_complete": False,
            "evidence_errors": ["account_risk_cache_unavailable"],
            "error_code": "account_risk_cache_unavailable",
        }

    def get_cached_account_risk_snapshot(self) -> Dict[str, Any]:
        """Return callback-safe risk evidence and schedule refresh without network I/O."""
        with self._account_risk_lock:
            snapshot = (
                deepcopy(self._last_account_risk_snapshot)
                if self._last_account_risk_snapshot is not None
                and self._last_account_risk_snapshot_generation == self._stream_generation
                else None
            )
        self.enqueue_account_risk_refresh()
        return snapshot if snapshot is not None else self._cached_account_risk_unavailable()

    def get_account_risk_snapshot(self) -> Dict[str, Any]:
        """Return SDK-owned durable account-loss evidence or an explicit blocker.

        The Store deliberately does not synthesize a durable baseline or
        realised PnL from Backtrader's process-local cash/value fields.  A
        provider without the public SDK contract therefore returns a complete
        fail-closed shape with ``evidence_complete=False``.
        """
        with self._account_risk_lock:
            cached = (
                deepcopy(self._last_account_risk_snapshot)
                if self._last_account_risk_snapshot is not None
                and self._last_account_risk_snapshot_generation == self._stream_generation
                else None
            )
        if cached is not None and (self._started or self._api is None):
            return cached
        return self._read_account_risk_snapshot(self._api)

    def initialize_account_risk_baseline(self) -> Dict[str, Any]:
        """Ask the SDK to initialize its baseline under its authoritative flatness gate."""
        if not self.requires_account_risk:
            raise BtApiStoreError("account_risk_not_required")
        snapshot = self._read_account_risk_snapshot(
            self._ensure_api_ready(), initialize_baseline=True
        )
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("durable") is not True
            or snapshot.get("trading_blocked") is not False
        ):
            raise BtApiStoreError("account_risk_baseline_not_proven")
        return snapshot

    def get_reconcile_snapshot(self) -> Dict[str, Any]:
        """Return one redacted, identity-bound synchronous SDK reconciliation snapshot."""
        if not self._sdk_mode:
            raise BtApiStoreError("SDK reconciliation is unavailable")
        incident_epoch = self._current_risk_incident_epoch()
        snapshot = self._sdk_reconcile_snapshot()
        self._maybe_clear_risk_state_latch(snapshot, incident_epoch=incident_epoch)
        return cast(Dict[str, Any], self.redact_runtime_value(snapshot))

    def _read_account_risk_snapshot(
        self, api: Any, *, initialize_baseline: bool = False
    ) -> Dict[str, Any]:
        """Read, validate and redact the public SDK account-risk contract."""
        configured_routes = sorted(
            str(venue).strip() for venue in self._sdk_exchanges if str(venue).strip()
        )
        configured_venues = sorted(
            {
                str(venue).partition("___")[0].strip().lower()
                for venue in configured_routes
                if str(venue).strip()
            }
        )

        def unavailable(error_code: str, errors: Optional[Iterable[str]] = None):
            return self._cache_account_risk_snapshot(
                {
                    "schema_version": 1,
                    "baseline_equity": None,
                    "current_equity": None,
                    "realized_net": None,
                    "configured_venues": configured_venues,
                    "configured_venue_routes": configured_routes,
                    "baseline_equity_by_venue": None,
                    "current_equity_by_venue": None,
                    "currency": None,
                    "generation": 0,
                    "fencing_epoch": 0,
                    "as_of_monotonic_ns": 0,
                    "owner_pid": None,
                    "clock_domain_id": "",
                    "identity_binding_sha256": "",
                    "durable": False,
                    "trading_blocked": True,
                    "loss_limit_bps": self._sdk_execution_config.get("account_maximum_loss_bps"),
                    "loss_limit_breached": False,
                    "loss_breached_at": None,
                    "loss_amount": None,
                    "loss_limit_amount": None,
                    "loss_bps_observed": None,
                    "peak_loss_bps": None,
                    "evidence_complete": False,
                    "evidence_errors": list(errors or (error_code,)),
                    "error_code": error_code,
                }
            )

        # Validate the immutable identity vector before asking the SDK to
        # create a durable baseline. A wrong injected SDK must not mutate a
        # different ledger before the mismatch is discovered.
        execution_identities = {}
        identity_errors = []
        for venue in configured_routes:
            try:
                execution_identities[venue] = self._validated_sdk_identity(venue)
            except BtApiStoreError as exc:
                identity_errors.append(f"{venue}:{exc}")
        if identity_errors or len(execution_identities) != len(configured_routes):
            return unavailable("account_risk_identity_unproven", identity_errors)

        getter = getattr(api, "get_account_risk_snapshot", None)
        if not callable(getter):
            return unavailable("account_risk_snapshot_unavailable")
        risk_read_started_ns = time.monotonic_ns()
        try:
            raw_snapshot = getter(initialize_baseline=True) if initialize_baseline else getter()
            risk_read_finished_ns = time.monotonic_ns()
            snapshot = _contract_mapping(raw_snapshot, "account risk snapshot")
        except Exception as exc:
            self.sanitize_exception(exc)
            return unavailable(self._safe_exception_code(exc, "account_risk_snapshot_failed"))

        required = {
            "schema_version",
            "baseline_equity",
            "baseline_equity_by_venue",
            "blocked_reasons",
            "clock_domain_id",
            "currency",
            "current_equity",
            "current_equity_by_venue",
            "configured_venues",
            "evidence_errors",
            "ledger_identities",
            "generation",
            "fencing_epoch",
            "as_of_monotonic_ns",
            "owner_pid",
            "durable",
            "trading_blocked",
            "evidence_complete",
            "loss_limit_bps",
            "loss_limit_breached",
            "loss_breached_at",
            "loss_amount",
            "loss_limit_amount",
            "loss_bps_observed",
            "peak_loss_bps",
        }
        errors = [f"missing_{key}" for key in sorted(required.difference(snapshot))]
        raw_routes = snapshot.get("configured_venues")
        if isinstance(raw_routes, (list, tuple)) and all(
            isinstance(venue, str) and venue.strip() for venue in raw_routes
        ):
            actual_routes = sorted(venue.strip() for venue in raw_routes)
            if len(actual_routes) != len(set(actual_routes)):
                errors.append("duplicate_configured_venues")
        else:
            actual_routes = []
            errors.append("invalid_configured_venues")
        if actual_routes != configured_routes:
            errors.append("configured_venues_mismatch")
        snapshot["configured_venue_routes"] = actual_routes
        snapshot["configured_venues"] = sorted(
            {self._public_sdk_venue(venue) for venue in actual_routes}
        )

        # Re-read every identity after the SDK call; the per-session binding
        # rejects a time-of-check/time-of-use account or fence change.
        post_call_identities = {}
        for venue in configured_routes:
            try:
                post_call_identities[venue] = self._validated_sdk_identity(venue)
            except BtApiStoreError as exc:
                errors.append(f"{venue}:{exc}")
        if len(post_call_identities) == len(configured_routes):
            execution_identities = post_call_identities
        identity_binding_sha256 = (
            self._sdk_identity_binding_sha256(execution_identities)
            if len(execution_identities) == len(configured_routes)
            else ""
        )
        snapshot["identity_binding_sha256"] = identity_binding_sha256

        raw_ledger_identities = snapshot.get("ledger_identities")
        if not isinstance(raw_ledger_identities, list):
            errors.append("invalid_ledger_identities")
            raw_ledger_identities = []

        def account_identity(identity):
            canonical = self._canonical_sdk_identity(identity)
            result = {key: canonical[key] for key in ("provider", "environment", "account_id")}
            if canonical.get("credential_fingerprint"):
                result["credential_fingerprint"] = canonical["credential_fingerprint"]
            return result

        expected_account_identities = sorted(
            (account_identity(identity) for identity in execution_identities.values()),
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")),
        )
        expected_identity_keys = [
            json.dumps(row, sort_keys=True, separators=(",", ":"))
            for row in expected_account_identities
        ]
        if len(expected_identity_keys) != len(set(expected_identity_keys)):
            errors.append("duplicate_account_risk_identity")
        actual_account_identities = []
        for raw_identity in raw_ledger_identities:
            if not isinstance(raw_identity, Mapping):
                errors.append("invalid_ledger_identity")
                continue
            actual_account_identities.append(account_identity(raw_identity))
        actual_account_identities.sort(
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))
        )
        if actual_account_identities != expected_account_identities:
            errors.append("account_risk_identity_mismatch")

        if type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != 1:
            errors.append("invalid_schema_version")

        def equity_map(key):
            raw = snapshot.get(key)
            if not isinstance(raw, Mapping):
                errors.append(f"invalid_{key}")
                return None, set()
            if set(raw) != set(configured_routes):
                errors.append(f"{key}_venues_mismatch")
            total = Decimal(0)
            currencies = set()
            valid = True
            for venue in configured_routes:
                row = raw.get(venue)
                if not isinstance(row, Mapping):
                    errors.append(f"invalid_{key}_{venue}")
                    valid = False
                    continue
                currency = str(row.get("currency") or "").strip().upper()
                if not currency:
                    errors.append(f"invalid_{key}_{venue}_currency")
                    valid = False
                else:
                    currencies.add(currency)
                try:
                    value = Decimal(str(row.get("equity")))
                    if not value.is_finite():
                        raise InvalidOperation
                    total += value
                except (InvalidOperation, TypeError, ValueError):
                    errors.append(f"invalid_{key}_{venue}_equity")
                    valid = False
            return (total if valid else None), currencies

        baseline_total, baseline_currencies = equity_map("baseline_equity_by_venue")
        current_total, current_currencies = equity_map("current_equity_by_venue")
        aggregate_values = {}
        for key in ("baseline_equity", "current_equity"):
            try:
                value = Decimal(str(snapshot.get(key)))
                if not value.is_finite():
                    raise InvalidOperation
                aggregate_values[key] = value
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"invalid_{key}")
        if baseline_total is not None and aggregate_values.get("baseline_equity") != baseline_total:
            errors.append("baseline_equity_aggregate_mismatch")
        if current_total is not None and aggregate_values.get("current_equity") != current_total:
            errors.append("current_equity_aggregate_mismatch")

        configured_loss_limit = self._sdk_execution_config.get("account_maximum_loss_bps")
        raw_loss_limit = snapshot.get("loss_limit_bps")
        loss_limit = None
        if configured_loss_limit is None:
            if raw_loss_limit is not None:
                errors.append("unexpected_account_maximum_loss_limit")
        else:
            try:
                configured_loss_limit = Decimal(str(configured_loss_limit))
                loss_limit = Decimal(str(raw_loss_limit))
                if (
                    not configured_loss_limit.is_finite()
                    or configured_loss_limit <= 0
                    or not loss_limit.is_finite()
                    or loss_limit <= 0
                    or loss_limit != configured_loss_limit
                ):
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                errors.append("account_maximum_loss_limit_mismatch")

        loss_limit_breached = snapshot.get("loss_limit_breached")
        if type(loss_limit_breached) is not bool:
            errors.append("invalid_loss_limit_breached")
        loss_breached_at = snapshot.get("loss_breached_at")
        if loss_limit_breached is True:
            if (
                isinstance(loss_breached_at, bool)
                or not isinstance(loss_breached_at, (int, float))
                or not math.isfinite(loss_breached_at)
                or loss_breached_at <= 0
            ):
                errors.append("invalid_loss_breached_at")
        elif loss_breached_at is not None:
            errors.append("unexpected_loss_breached_at")

        loss_values: Dict[str, Any] = {}
        for key in (
            "loss_amount",
            "loss_limit_amount",
            "loss_bps_observed",
            "peak_loss_bps",
        ):
            raw_value = snapshot.get(key)
            if raw_value is None:
                loss_values[key] = None
                continue
            try:
                value = Decimal(str(raw_value))
                if not value.is_finite() or value < 0 or not isinstance(raw_value, str):
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"invalid_{key}")
                loss_values[key] = None
            else:
                loss_values[key] = value

        if loss_limit is None:
            if loss_limit_breached is not False or any(
                value is not None for value in loss_values.values()
            ):
                errors.append("unexpected_account_loss_state")
        elif baseline_total is not None and current_total is not None and baseline_total > 0:
            expected_loss = max(baseline_total - current_total, Decimal("0"))
            expected_limit_amount = baseline_total * loss_limit / Decimal("10000")
            expected_loss_bps = expected_loss * Decimal("10000") / baseline_total
            if loss_values["loss_amount"] != expected_loss:
                errors.append("account_loss_amount_mismatch")
            if loss_values["loss_limit_amount"] != expected_limit_amount:
                errors.append("account_loss_limit_amount_mismatch")
            if loss_values["loss_bps_observed"] != expected_loss_bps:
                errors.append("account_loss_bps_mismatch")
            peak = loss_values["peak_loss_bps"]
            if peak is None or peak < expected_loss_bps:
                errors.append("account_peak_loss_bps_mismatch")
            if loss_limit_breached is False and expected_loss_bps >= loss_limit:
                errors.append("account_loss_latch_missing")
        aggregate_currency = snapshot.get("currency")
        if not isinstance(aggregate_currency, str) or not aggregate_currency.strip():
            errors.append("invalid_currency")
        else:
            aggregate_currency = aggregate_currency.strip().upper()
            if baseline_currencies != {aggregate_currency} or current_currencies != {
                aggregate_currency
            }:
                errors.append("account_risk_currency_mismatch")
            snapshot["currency"] = aggregate_currency
        if snapshot.get("realized_net") is not None:
            try:
                if not Decimal(str(snapshot["realized_net"])).is_finite():
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                errors.append("invalid_realized_net")
        for key in ("generation", "fencing_epoch", "as_of_monotonic_ns", "owner_pid"):
            fence_value = snapshot.get(key)
            if type(fence_value) is not int or fence_value <= 0:
                errors.append(f"invalid_{key}")
        if snapshot.get("generation") != snapshot.get("fencing_epoch"):
            errors.append("account_risk_generation_fence_mismatch")
        owner_pid = snapshot.get("owner_pid")
        clock_domain_id = snapshot.get("clock_domain_id")
        if owner_pid != os.getpid() or clock_domain_id != f"process:{owner_pid}:monotonic":
            errors.append("account_risk_clock_domain_mismatch")
        as_of_monotonic_ns = snapshot.get("as_of_monotonic_ns")
        if type(as_of_monotonic_ns) is int:
            if as_of_monotonic_ns < risk_read_started_ns:
                errors.append("account_risk_timestamp_precedes_call")
            elif as_of_monotonic_ns > risk_read_finished_ns:
                errors.append("account_risk_timestamp_in_future")
        for key in ("durable", "trading_blocked", "evidence_complete"):
            if not isinstance(snapshot.get(key), bool):
                errors.append(f"invalid_{key}")
        sdk_evidence_errors = snapshot.get("evidence_errors")
        if not isinstance(sdk_evidence_errors, Mapping):
            errors.append("invalid_sdk_evidence_errors")
        elif sdk_evidence_errors:
            errors.append("sdk_evidence_errors_present")
        blocked_reasons = snapshot.get("blocked_reasons")
        if not isinstance(blocked_reasons, list):
            errors.append("invalid_blocked_reasons")
        elif blocked_reasons:
            errors.append("sdk_blocked_reasons_present")
        if snapshot.get("durable") is not True:
            errors.append("account_risk_not_durable")
        if snapshot.get("trading_blocked") is not False:
            errors.append("account_risk_trading_blocked")
        if snapshot.get("evidence_complete") is not True:
            errors.append("sdk_evidence_incomplete")

        risk_fence = snapshot.get("fencing_epoch")
        execution_fences = {
            identity.get("fencing_epoch") for identity in execution_identities.values()
        }
        if len(execution_fences) != 1 or risk_fence not in execution_fences:
            errors.append("account_risk_fencing_epoch_mismatch")

        if errors or snapshot.get("evidence_complete") is not True:
            snapshot.update(
                durable=False,
                trading_blocked=True,
                evidence_complete=False,
                evidence_errors=sorted(set(errors or ("sdk_evidence_incomplete",))),
                error_code="account_risk_evidence_incomplete",
            )
        return self._cache_account_risk_snapshot(snapshot)

    def _sdk_exchange(self, dataname):
        """Resolve a Backtrader feed binding to an SDK exchange name."""
        venue = self._sdk_routes.get(str(dataname))
        if venue is None and len(self._sdk_exchanges) == 1:
            venue = next(iter(self._sdk_exchanges))
        if venue not in self._sdk_exchanges:
            raise BtApiStoreError("A symbol_routes entry is required for this feed")
        return venue

    def _sdk_account_id(self, venue, supplied=None):
        """Resolve an authenticated account through the SDK-owned ledger identity."""
        identity = self._validated_sdk_identity(venue)
        account_id = str(identity.get("account_id") or "")
        if supplied not in (None, ""):
            supplied_id = str(supplied).strip().casefold()
            allowed = {account_id.casefold()}
            account_alias = identity.get("account_alias")
            if account_alias not in (None, ""):
                allowed.add(str(account_alias).strip().casefold())
            if supplied_id not in allowed:
                raise BtApiStoreError("The requested account_id does not match the SDK ledger")
        return account_id

    def _warm_sdk_command_types(self) -> Dict[str, Any]:
        """Load public bt_api_py request models outside the order hot path."""
        if not self._sdk_command_types:
            from bt_api_py import (
                CancelOrderRequest,
                OrderRequest,
                OrderType,
                QueryOrderRequest,
                Side,
            )

            self._sdk_command_types.update(
                CancelOrderRequest=CancelOrderRequest,
                OrderRequest=OrderRequest,
                OrderType=OrderType,
                QueryOrderRequest=QueryOrderRequest,
                Side=Side,
            )
        return self._sdk_command_types

    def get_symbol_routes(self) -> Dict[str, str]:
        """Return a copy of the framework symbol-to-SDK venue bindings."""
        return dict(self._sdk_routes)

    def _sdk_order_request(self, venue, payload):
        """Convert a framework Order and bind its reference before the SDK call."""
        command_types = self._warm_sdk_command_types()
        OrderRequest = command_types["OrderRequest"]
        OrderType = command_types["OrderType"]
        Side = command_types["Side"]

        account_id = self._sdk_account_id(venue)
        client_id = str(payload.get("client_order_id") or self._api.new_client_order_id(venue))
        strategy_identity_sha256 = str(
            self._sdk_execution_config.get("strategy_identity_sha256") or ""
        )
        supplied_strategy_identity = str(payload.get("strategy_identity_sha256") or "")
        if supplied_strategy_identity and supplied_strategy_identity != strategy_identity_sha256:
            raise BtApiStoreError("Order strategy identity differs from SDK execution config")
        binding = {
            "symbol": payload["symbol"],
            "exchange_name": venue,
            "account_id": account_id,
            "client_order_id": client_id,
            "bt_order_ref": payload.get("bt_order_ref"),
        }
        previous = self._sdk_client_refs.get((venue, client_id))
        if previous and previous.get("bt_order_ref") != binding["bt_order_ref"]:
            raise BtApiStoreError("client_order_id is already bound to another Backtrader order")
        request = OrderRequest(
            symbol=payload["symbol"],
            account_id=account_id,
            client_order_id=client_id,
            side=Side(payload["side"]),
            order_type=OrderType(payload["order_type"]),
            quantity=Decimal(str(payload["size"])),
            price=Decimal(str(payload["price"])) if payload.get("price") is not None else None,
            quantity_unit=(
                payload.get("quantity_unit")
                or self.contract_metadata.get(payload["symbol"], {}).get("quantity_unit")
                or "native"
            ),
            time_in_force=str(payload.get("time_in_force", "GTC")).upper(),
            reduce_only=bool(payload.get("reduce_only", False)),
            **{
                key: payload[key]
                for key in (
                    "position_side",
                    "position_id",
                    "offset",
                    "exchange_id",
                    "position_mode",
                    "execution_cycle_id",
                    "execution_role",
                )
                if payload.get(key) is not None
            },
            **(
                {"strategy_identity_sha256": strategy_identity_sha256}
                if strategy_identity_sha256
                else {}
            ),
        )

        def public_value(value):
            return getattr(value, "value", value)

        binding["execution_contract"] = {
            "side": str(public_value(request.side)).strip().lower(),
            "position_side": public_value(getattr(request, "position_side", None)),
            "offset": public_value(getattr(request, "offset", None)),
            "position_mode": public_value(getattr(request, "position_mode", None)),
            "quantity_unit": str(public_value(request.quantity_unit)).strip().lower(),
            "requested_quantity": str(request.quantity),
            "reduce_only": bool(request.reduce_only),
            "strategy_identity_sha256": getattr(request, "strategy_identity_sha256", None),
            "execution_cycle_id": getattr(request, "execution_cycle_id", None),
            "execution_role": getattr(request, "execution_role", None),
        }
        self._sdk_client_refs[(venue, client_id)] = binding
        self._sdk_local_refs[str(binding["bt_order_ref"])] = binding
        return request

    def _sdk_broker_event(self, venue, event):
        """Attach framework identity without interpreting execution state or fees."""
        result = dict(event)
        client_id = str(result.get("client_order_id") or result.get("order_ref") or "")
        order_id = str(result.get("order_id") or "")
        binding = self._sdk_client_refs.get((venue, client_id)) or (
            self._sdk_venue_refs.get((venue, order_id)) if order_id else None
        )
        if binding is None:
            binding = {
                "symbol": result["symbol"],
                "exchange_name": venue,
                "account_id": self._sdk_account_id(venue),
                "client_order_id": client_id,
                "bt_order_ref": None,
            }
        for key in ("order_id", "order_ref", "exchange_id", "front_id", "session_id"):
            if result.get(key) not in (None, ""):
                binding[key] = result[key]
        if client_id:
            self._sdk_client_refs[(venue, client_id)] = binding
        if order_id:
            self._sdk_venue_refs[(venue, order_id)] = binding
        result.update(
            data_name=binding["symbol"],
            bt_order_ref=binding.get("bt_order_ref"),
            external_order_id=f"{venue}:{order_id}" if order_id else None,
            venue_order_id=order_id,
        )
        return result

    def _sdk_cancel_request(self, reference, dataname):
        """Translate local/scoped references into the SDK's public cancellation type."""
        CancelOrderRequest = self._warm_sdk_command_types()["CancelOrderRequest"]

        reference = str(reference)
        venue = self._sdk_exchange(dataname) if dataname is not None else None
        binding = self._sdk_local_refs.get(reference)
        if binding is None:
            candidates = [
                item
                for key, item in self._sdk_client_refs.items()
                if key[1] == reference and (venue is None or key[0] == venue)
            ]
            candidates += [
                item
                for (name, order_id), item in self._sdk_venue_refs.items()
                if (reference == f"{name}:{order_id}" or reference == order_id)
                and (venue is None or name == venue)
            ]
            if candidates and all(item is candidates[0] for item in candidates):
                binding = candidates[0]
        if binding is None or (venue is not None and binding["exchange_name"] != venue):
            raise BtApiStoreError("The cancellation reference has no unambiguous feed binding")
        venue = binding["exchange_name"]
        request = CancelOrderRequest(
            symbol=binding["symbol"],
            account_id=self._sdk_account_id(venue, binding.get("account_id")),
            client_order_id=binding.get("client_order_id") or None,
            **{
                key: binding[key]
                for key in (
                    "order_id",
                    "order_ref",
                    "exchange_id",
                    "front_id",
                    "session_id",
                )
                if binding.get(key) not in (None, "")
            },
        )
        return venue, request

    def _sdk_query_request(self, reference, dataname):
        """Translate a framework/scoped reference into the SDK query contract."""
        QueryOrderRequest = self._warm_sdk_command_types()["QueryOrderRequest"]

        reference = str(reference)
        venue = self._sdk_exchange(dataname) if dataname is not None else None
        binding = self._sdk_local_refs.get(reference)
        if binding is None:
            candidates = [
                item
                for key, item in self._sdk_client_refs.items()
                if key[1] == reference and (venue is None or key[0] == venue)
            ]
            candidates += [
                item
                for (name, order_id), item in self._sdk_venue_refs.items()
                if (reference == f"{name}:{order_id}" or reference == order_id)
                and (venue is None or name == venue)
            ]
            if candidates and all(item is candidates[0] for item in candidates):
                binding = candidates[0]
        if binding is None or (venue is not None and binding["exchange_name"] != venue):
            raise BtApiStoreError("The query reference has no unambiguous feed binding")
        venue = binding["exchange_name"]
        request = QueryOrderRequest(
            symbol=binding["symbol"],
            account_id=self._sdk_account_id(venue, binding.get("account_id")),
            client_order_id=binding.get("client_order_id") or None,
            **{
                key: binding[key]
                for key in (
                    "order_id",
                    "order_ref",
                    "exchange_id",
                    "front_id",
                    "session_id",
                )
                if binding.get(key) not in (None, "")
            },
        )
        return venue, request, binding

    def _apply_sdk_account_push(self, venue, event):
        """Refresh cached venue cash/value from a partial WSS account push.

        Single-denomination pushes carry top-level ``cash``/``value`` and may
        replace the stale REST snapshot for this venue only; multi-coin pushes
        stay audit-only. Local order/position accounting is never touched.
        """
        cash, value = event.get("cash"), event.get("value")
        if not isinstance(cash, (int, float)) or not isinstance(value, (int, float)):
            self.emit_runtime_event("venue_account_update", venue=venue)
            return
        cache = dict(self._venue_balance_cache.get(venue) or {})
        cache.update(cash=float(cash), value=float(value))
        self._venue_balance_cache[venue] = cache
        self._last_venue_balance_refresh = time.monotonic()
        self.emit_runtime_event("venue_account_update", venue=venue)

    def get_orderbook_drop_counts(self):
        """Return per-symbol counts of books evicted by bounded depth queues."""
        return dict(self._sdk_book_drops)

    @staticmethod
    def _market_event_kind(event: Any) -> str:
        """Return the canonical market kind without interpreting venue payloads."""
        if isinstance(event, Mapping):
            return str(event.get("kind") or "market").lower()
        return str(getattr(event, "event_type", "market") or "market").lower()

    def _mark_feed_inflight(self, event: Any) -> None:
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            return
        kind = self._market_event_kind(event)
        self._stream_health[symbol][f"{kind}_feed_inflight"] += 1

    def _record_market_drop(
        self,
        event: Any,
        reason: str,
        *,
        safety_impact: str = "stream_marked_stale",
        mark_stale: bool = True,
    ) -> None:
        """Record one canonical market event as explicitly discarded."""
        getter = (
            event.get
            if isinstance(event, Mapping)
            else lambda key, default=None: getattr(event, key, default)
        )
        symbol = str(getter("symbol", "") or "")
        if not symbol:
            return
        kind = self._market_event_kind(event)
        event_id = str(getter("event_id", "") or "")
        counters = self._stream_health[symbol]
        counters["store_dropped"] += 1
        counters[f"{kind}_store_dropped"] += 1
        state = self._stream_state[symbol]
        state.update(
            last_drop_event_id=event_id,
            last_drop_kind=kind,
            last_drop_reason=str(reason),
        )
        if mark_stale:
            state.update(
                stale=True,
                stale_reason=str(reason),
                continuity_status="gap",
            )
        self._market_drop_records[symbol].append(
            {
                "event_id": event_id,
                "kind": kind,
                "reason": str(reason),
                "safety_impact": str(safety_impact),
                "stream_generation": self._stream_generation,
            }
        )

    def mark_feed_dropped(self, event: Any, reason: str) -> None:
        """Close a polled event's accounting when the Feed cannot dispatch it."""
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            return
        event_id = str(getattr(event, "event_id", "") or "")
        dropped = self._feed_dropped_ids[symbol]
        if event_id and event_id in dropped:
            dropped.move_to_end(event_id)
            self._stream_health[symbol]["feed_drop_alias"] += 1
            return
        if event_id:
            dropped[event_id] = None
            if len(dropped) > self._strategy_delivery_id_limit:
                dropped.popitem(last=False)
        kind = self._market_event_kind(event)
        inflight_key = f"{kind}_feed_inflight"
        if self._stream_health[symbol][inflight_key] > 0:
            self._stream_health[symbol][inflight_key] -= 1
        self._record_market_drop(event, reason, safety_impact="event_not_visible_to_strategy")

    def mark_strategy_delivered(self, event: Any) -> None:
        """Account for a standard event after its strategy callback returns."""
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            return
        event_id = str(getattr(event, "event_id", "") or "")
        if event_id:
            delivered = self._strategy_delivered_ids[symbol]
            if event_id in delivered:
                delivered.move_to_end(event_id)
                self._stream_health[symbol]["strategy_delivery_alias"] += 1
                return
            delivered[event_id] = None
            if len(delivered) > self._strategy_delivery_id_limit:
                delivered.popitem(last=False)
        counters = self._stream_health[symbol]
        kind = self._market_event_kind(event)
        inflight_key = f"{kind}_feed_inflight"
        if counters[inflight_key] > 0:
            counters[inflight_key] -= 1
        counters["strategy_delivered"] += 1
        counters[f"{kind}_strategy_delivered"] += 1

    def get_stream_health(self, dataname: Optional[str] = None) -> Dict[str, Any]:
        """Return causal stream counters and the current fail-closed state."""
        symbols = (
            [str(dataname)]
            if dataname is not None
            else sorted(set(self._stream_health) | set(self._stream_state))
        )
        result = {}
        for symbol in symbols:
            counters = dict(self._stream_health[symbol])
            state = dict(self._stream_state[symbol])
            book_ingress = counters.get("orderbook_sdk_ingress", 0)
            book_coalesced = counters.get("orderbook_sdk_coalesced", 0)
            book_dropped = counters.get("orderbook_store_dropped", 0)
            book_delivered = counters.get("orderbook_strategy_delivered", 0)
            book_inflight = counters.get("orderbook_feed_inflight", 0)
            book_queue_depth = len(self._sdk_books[symbol])
            result[symbol] = {
                **counters,
                **state,
                "book_queue_depth": book_queue_depth,
                "tick_queue_depth": len(self._sdk_ticks[symbol]),
                "store_dropped": counters.get("store_dropped", 0),
                "strategy_delivered": counters.get("strategy_delivered", 0),
                "sdk_ingress": counters.get("sdk_ingress", 0),
                "sdk_coalesced": counters.get("sdk_coalesced", 0),
                "book_ingress": book_ingress,
                "book_coalesced": book_coalesced,
                "book_dropped": book_dropped,
                "book_strategy_delivered": book_delivered,
                "book_feed_inflight": book_inflight,
                "book_conservation": (
                    book_ingress
                    == book_coalesced
                    + book_dropped
                    + book_delivered
                    + book_inflight
                    + book_queue_depth
                ),
                "market_drop_records": list(self._market_drop_records[symbol]),
                "stream_generation": self._stream_generation,
                "stale": bool(state.get("stale", False)),
            }
        if dataname is not None:
            return result.get(str(dataname), {"stale": False})
        return result

    def is_stream_ready(self, dataname: str) -> bool:
        """Return false after an explicit gap, stale event, disconnect, or drop."""
        return not bool(self._stream_state[str(dataname)].get("stale", False))

    def _record_sdk_market_event(self, venue: str, raw_event: Mapping[str, Any]):
        """Attach Store-side continuity evidence without decoding venue protocols."""
        event = dict(raw_event)
        event.setdefault("received_monotonic_ns", event.get("recv_monotonic_ns"))
        event.setdefault("sequence", event.get("ingest_seq", 0))
        event.setdefault("volume", event.get("delta_volume"))
        event.setdefault("price", event.get("last_price"))
        event.setdefault("bid_volume", event.get("bid_size"))
        event.setdefault("ask_volume", event.get("ask_size"))
        symbol = str(event.get("symbol") or "")
        if not symbol:
            return None
        counters = self._stream_health[symbol]
        state = self._stream_state[symbol]
        try:
            coalesced_count = max(int(event.get("coalesced_count", 1) or 1), 1)
        except (TypeError, ValueError):
            coalesced_count = 1
        counters["sdk_ingress"] += coalesced_count
        counters["sdk_coalesced"] += coalesced_count - 1
        kind = str(event.get("kind") or "market").lower()
        counters[f"{kind}_sdk_ingress"] += coalesced_count
        counters[f"{kind}_sdk_coalesced"] += coalesced_count - 1
        event["coalesced_count"] = coalesced_count
        event.setdefault("event_id", uuid.uuid4().hex)
        received_monotonic_ns = event.get("received_monotonic_ns")
        clock_domain_id = event.get("clock_domain_id")
        if (
            isinstance(received_monotonic_ns, bool)
            or not isinstance(received_monotonic_ns, int)
            or received_monotonic_ns <= 0
            or not isinstance(clock_domain_id, str)
            or not clock_domain_id.strip()
        ):
            # Receive-clock provenance belongs to bt_api_py, where the raw
            # transport event first enters the unified interface.  Restamping
            # it here would make unrelated clocks appear comparable.
            self._record_market_drop(event, "causal_provenance_missing_or_invalid")
            return None
        event["clock_domain_id"] = clock_domain_id.strip()
        event.setdefault("received_wall_time", event.get("local_time") or time.time())
        event.setdefault("exchange_time", event.get("timestamp"))
        event.setdefault("source", "bt_api_py")
        raw_snapshot_kind = event.get("snapshot_or_delta")
        raw_continuity = event.get("continuity_status") or event.get("continuity")
        raw_sequence = event.get("sequence")
        raw_previous_sequence = event.get("previous_sequence")
        if kind == "orderbook":
            try:
                _, _, normalize_orderbook_evidence = _sdk_cross_venue_contracts()
                sequence, previous_sequence, snapshot_kind, continuity = (
                    normalize_orderbook_evidence(
                        raw_sequence,
                        raw_previous_sequence,
                        raw_snapshot_kind,
                        raw_continuity,
                    )
                )
            except (BtApiStoreError, ValueError) as exc:
                self._record_market_drop(event, str(exc))
                return None
        else:
            snapshot_kind = str(raw_snapshot_kind or "snapshot").strip().lower()
            continuity = str(raw_continuity or "unknown").strip().lower()
            try:
                sequence = int(raw_sequence or 0)
            except (TypeError, ValueError):
                sequence = 0
            try:
                previous_sequence = (
                    int(raw_previous_sequence) if raw_previous_sequence not in (None, "") else None
                )
            except (TypeError, ValueError):
                previous_sequence = None
        event["snapshot_or_delta"] = snapshot_kind
        event["continuity_status"] = continuity
        explicit_stale = bool(event.get("stale", False))
        stale_reason = str(event.get("stale_reason") or "")
        sequence_key = (venue, symbol)
        previous_seen = self._sdk_sequences.get(sequence_key)
        event["sequence"] = sequence
        event["previous_sequence"] = previous_sequence

        is_snapshot = event["snapshot_or_delta"] == "snapshot"
        if sequence and previous_seen is not None and not is_snapshot:
            if sequence < previous_seen:
                counters["out_of_order"] += 1
                self._record_market_drop(event, "sequence_out_of_order")
                return None
            if sequence == previous_seen:
                counters["duplicate"] += 1
                self._record_market_drop(
                    event,
                    "duplicate_sequence",
                    safety_impact="duplicate_removed_without_state_change",
                    mark_stale=False,
                )
                return None
            if previous_sequence is not None and previous_sequence != previous_seen:
                continuity = "gap"
                stale_reason = "sequence_gap"

        event["_sequence_key"] = sequence_key
        event["_sequence_value"] = sequence
        unhealthy = continuity in {
            "gap",
            "stale",
            "disconnected",
            "checksum_failed",
            "out_of_order",
        }
        if unhealthy:
            counters["sequence_gap" if continuity == "gap" else continuity] += 1
            explicit_stale = True
            stale_reason = stale_reason or continuity
        if explicit_stale:
            counters["stale"] += 1
            state.update(stale=True, stale_reason=stale_reason or "stale_event")
            event.update(stale=True, stale_reason=state["stale_reason"])
        elif is_snapshot and continuity in {"ok", "continuous", "recovered", "snapshot"}:
            # Snapshot recovery is provisional until the native object validates.
            # Otherwise a crossed/empty book can falsely clear a prior gap.
            event["_recovery_candidate"] = True
            if state.get("stale"):
                event.update(
                    stale=True,
                    stale_reason=state.get("stale_reason") or "recovery_pending_validation",
                )
            else:
                event.update(stale=False, stale_reason="")
        elif state.get("stale"):
            # A continuous delta cannot recover a previously broken book. Keep
            # every delivered event unsafe until the SDK emits a valid snapshot.
            event.update(stale=True, stale_reason=state.get("stale_reason") or "stale_stream")
        state.update(
            continuity_status=(
                "recovery_pending" if event.get("_recovery_candidate") else continuity
            ),
            last_event_id=event["event_id"],
            clock_domain_id=event["clock_domain_id"],
            last_received_monotonic_ns=event["received_monotonic_ns"],
        )
        event["continuity_status"] = continuity
        return event

    def _accept_sdk_market_event(self, event: Mapping[str, Any], native_event: Any) -> None:
        """Commit sequence and recovery state only after native validation succeeds."""
        sequence = event.get("_sequence_value")
        sequence_key = event.get("_sequence_key")
        if sequence and isinstance(sequence_key, tuple):
            self._sdk_sequences[sequence_key] = int(sequence)
        if not event.get("_recovery_candidate"):
            return
        symbol = str(event.get("symbol") or "")
        continuity = str(event.get("continuity_status") or "unknown")
        self._stream_state[symbol].update(
            stale=False,
            stale_reason="",
            continuity_status=continuity,
            last_event_id=str(event.get("event_id") or ""),
        )
        if isinstance(native_event, dict):
            native_event.update(stale=False, stale_reason="")
        else:
            native_event.stale = False
            native_event.stale_reason = ""

    def _mark_stream_disconnected(self, venue: str, event: Mapping[str, Any]) -> None:
        symbol = event.get("symbol")
        symbols = (
            [str(symbol)]
            if symbol
            else [name for name, route in self._sdk_routes.items() if route == venue]
        )
        for name in symbols:
            self._stream_health[name]["disconnect"] += 1
            self._stream_state[name].update(
                stale=True,
                stale_reason="stream_disconnected",
                continuity_status="disconnected",
            )

    def _drain_sdk_events(self):
        """Convert standard SDK events to native objects on the Cerebro thread."""
        for venue in self._sdk_exchanges:
            poll_events = getattr(self._api, "poll_events", None)
            if callable(poll_events):
                events = poll_events(
                    venue,
                    max_raw_items=(
                        self._sdk_event_batch_size if self.uses_async_commands else None
                    ),
                    coalesce_market_snapshots=(
                        self._sdk_coalesce_market_snapshots
                        if self.uses_async_commands
                        else ("orderbook",)
                    ),
                )
            else:
                events = []
                for _ in range(100):
                    event = self._api.poll_event(venue)
                    if event is None:
                        break
                    events.append(event)
            for event in events:
                kind, symbol = event["kind"], event.get("symbol")
                if kind in {"order", "trade"}:
                    self._append_sdk_update(self._sdk_broker_event(venue, event))
                elif kind == "account":
                    self._apply_sdk_account_push(venue, event)
                elif kind == "position":
                    # Position pushes are audit-only: startup-policy brokers
                    # own local leg accounting from confirmed fills.
                    self.emit_runtime_event("venue_position_update", venue=venue)
                elif kind in {"disconnect", "disconnected"}:
                    self._mark_stream_disconnected(venue, event)
                elif symbol in self._subscribed_datanames and self._sdk_exchange(symbol) == venue:
                    event = self._record_sdk_market_event(venue, event)
                    if event is None:
                        continue
                    common = {
                        key: event[key]
                        for key in (
                            "timestamp",
                            "symbol",
                            "exchange",
                            "asset_type",
                            "local_time",
                            "exchange_time",
                            "received_wall_time",
                            "received_monotonic_ns",
                            "clock_domain_id",
                            "sequence",
                            "previous_sequence",
                            "snapshot_or_delta",
                            "continuity_status",
                            "stale",
                            "stale_reason",
                            "source",
                            "event_id",
                            "coalesced_count",
                        )
                        if key in event
                    }
                    if kind == "orderbook":
                        try:
                            book = OrderBookSnapshot(
                                **common,
                                bids=event["bids"],
                                asks=event["asks"],
                            )
                        except (KeyError, TypeError, ValueError):
                            self._record_market_drop(event, "invalid_orderbook_snapshot")
                            continue
                        if not book.validate():
                            self._record_market_drop(event, "invalid_orderbook_snapshot")
                            continue
                        self._accept_sdk_market_event(event, book)
                        queue = self._sdk_books[symbol]
                        if queue.maxlen is not None and len(queue) >= queue.maxlen:
                            evicted = queue.popleft()
                            self._sdk_book_drops[symbol] = self._sdk_book_drops.get(symbol, 0) + 1
                            self._record_market_drop(
                                evicted,
                                "store_orderbook_queue_overflow",
                                safety_impact="newest_book_retained_but_stream_marked_stale",
                            )
                            self._stream_state[symbol]["last_enqueued_event_id"] = book.event_id
                            book.stale = True
                            book.stale_reason = "store_orderbook_queue_overflow"
                            book.continuity_status = "gap"
                        queue.append(book)
                    elif kind == "tick":
                        try:
                            tick = TickEvent(
                                **common,
                                **{
                                    key: event[key]
                                    for key in (
                                        "price",
                                        "volume",
                                        "direction",
                                        "trade_id",
                                        "bid_price",
                                        "ask_price",
                                        "bid_volume",
                                        "ask_volume",
                                    )
                                    if key in event
                                },
                            )
                        except (TypeError, ValueError):
                            self._record_market_drop(event, "invalid_tick")
                            continue
                        for key in (
                            "schema_version",
                            "volume_semantics",
                            "cum_volume",
                            "cumulative_volume",
                            "delta_volume",
                            "volume_complete",
                            "volume_quality",
                            "trading_day",
                            "action_day",
                            "event_time_utc",
                            "recv_time_utc",
                            "recv_monotonic_ns",
                            "connection_generation",
                            "ingest_seq",
                            "subscription_epoch",
                            "rules_hash",
                            "quality",
                            "quality_flags",
                            "event_time_source",
                            "source_clock_quality",
                            "receive_clock_quality",
                            "source_clock_error_ms",
                            "receive_clock_error_ms",
                            "freshness_verified",
                            "execution_eligible",
                            "cohort_now_monotonic_ns",
                            "cohort_now_epoch",
                            "cohort_now_clock_domain_id",
                            "cohort_now_receive_clock_error_ms",
                            "cohort_now_receive_clock_quality",
                            "cohort_now_freshness_verified",
                            "instrument_id",
                            "exchange_id",
                            # CTP contract identity is typed evidence, not
                            # optional presentation metadata.  In particular,
                            # the public cohort validator compares
                            # ``asset_type`` with ``contract_type`` to expose
                            # conflicting future/option labels.
                            "product_class",
                            "contract_type",
                            "option_type",
                            "underlying_instrument",
                            "strike_price",
                            "update_time",
                            "update_millisec",
                            "turnover",
                            "open_interest",
                            "lower_limit_price",
                            "upper_limit_price",
                        ):
                            if key in event:
                                setattr(tick, key, deepcopy(event[key]))
                        if not tick.validate():
                            self._record_market_drop(event, "invalid_tick")
                            continue
                        self._accept_sdk_market_event(event, tick)
                        queue = self._sdk_ticks[symbol]
                        if queue.maxlen is not None and len(queue) >= queue.maxlen:
                            evicted = queue.popleft()
                            self._sdk_tick_drops[symbol] = self._sdk_tick_drops.get(symbol, 0) + 1
                            self._record_market_drop(
                                evicted,
                                "store_tick_queue_overflow",
                                safety_impact="newest_tick_retained_but_stream_marked_stale",
                            )
                            self._stream_state[symbol]["last_enqueued_event_id"] = tick.event_id
                            tick.stale = True
                            tick.stale_reason = "store_tick_queue_overflow"
                            tick.continuity_status = "gap"
                        queue.append(tick)
                    elif kind == "bar":
                        self._accept_sdk_market_event(event, event)
                        self._live_bars[symbol].append(_normalize_bar(event))
                    else:
                        self._record_market_drop(
                            event,
                            "unsupported_market_event_kind",
                            safety_impact="event_not_consumed_by_store",
                        )

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
        if self._funding_restart_blocked_by_worker:
            self._prepare_funding_refresh_start()
        if self._sdk_mode and (self._restart_blocked_by_worker or self._restart_blocked_by_close):
            self._prepare_sdk_start()
        if self.provider in _PLACEHOLDER_PROVIDERS:
            raise BtApiProviderNotImplementedError(
                f"provider '{self.provider}' is reserved for future bt_api_py support"
            )

        if self._connected:
            return self._api

        if self._sdk_mode and not self._sdk_configured:
            options = {**self._config, **self._api_kwargs}
            execution = dict(self._sdk_execution_config)
            if self._api is None:
                # Creating a fresh owned client starts a new SDK session even
                # when the caller connects lazily rather than through start().
                self._last_account_risk_snapshot = None
                self._last_account_risk_snapshot_generation = None
                from bt_api_py import BtApi

                self._api = (self._api_cls or BtApi)(
                    exchange_kwargs=self._sdk_exchanges,
                    execution_config=execution,
                    debug=options.get("debug", False),
                    **{
                        key: options[key]
                        for key in ("transport_mode", "forwarding_config", "event_bus")
                        if key in options
                    },
                )
            elif "execution_config" in options or any(
                key in options for key in _SDK_EXECUTION_CONFIG_KEYS
            ):
                self._api.configure_execution(execution)
            self._sdk_configured = True
            self._last_execution_summary = None

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
            self.sanitize_exception(exc)
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
        try:
            self.get_balance()
        except Exception:
            self._connected = False
            if self._sdk_mode:
                api = self._api
                try:
                    get_execution_summary = getattr(api, "get_execution_summary", None)
                    if callable(get_execution_summary):
                        self._last_execution_summary = deepcopy(get_execution_summary())
                except Exception:
                    # Execution auditing is best effort while preserving the
                    # original account-readiness failure for the caller.
                    pass
                if api is not None:
                    closed, close_error = self._bounded_sdk_close(
                        api, self._command_shutdown_timeout
                    )
                    if closed and close_error is None:
                        self._shutdown_state = "PASS"
                if self._sdk_owned_api:
                    self._api = None
                self._sdk_configured = False
            elif hasattr(self._api, "disconnect"):
                self._api.disconnect()
            raise
        self.emit_runtime_event("store_ready", status="ready")
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

        info = getattr(order, "info", {})
        for key in (
            "time_in_force",
            "reduce_only",
            "client_order_id",
            "quantity_unit",
            "position_id",
            "position_mode",
            "front_id",
            "session_id",
            "order_ref",
            "execution_cycle_id",
            "execution_role",
            "strategy_identity_sha256",
        ):
            value = info.get(key)
            if value is not None:
                payload[key] = value

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
            wrapper_ok = status in {"ok", "success"} or code in {"0", "00000"} or success is True
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
