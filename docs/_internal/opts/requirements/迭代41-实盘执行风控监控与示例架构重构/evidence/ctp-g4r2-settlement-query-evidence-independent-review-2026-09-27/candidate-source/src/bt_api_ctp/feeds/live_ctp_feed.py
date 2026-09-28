from __future__ import annotations

import os
import threading
import time
import warnings
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from sys import float_info
from typing import Any

from bt_api_base.containers.orders.order import OrderStatus
from bt_api_base.containers.requestdatas.request_data import RequestData
from bt_api_base.exceptions import ExchangeConnectionAlias as BtConnectionError
from bt_api_base.feeds.capability import Capability
from bt_api_base.feeds.feed import Feed
from bt_api_base.logging_factory import get_logger

from bt_api_ctp.containers.ctp.ctp_account import CtpAccountData
from bt_api_ctp.containers.ctp.ctp_order import CtpOrderData
from bt_api_ctp.containers.ctp.ctp_position import CtpPositionData
from bt_api_ctp.containers.ctp.ctp_position_evidence import (
    CtpPositionEvidence,
    CtpPositionEvidenceError,
    build_ctp_position_evidence,
)
from bt_api_ctp.containers.ctp.ctp_ticker import CtpTickerData
from bt_api_ctp.containers.ctp.ctp_trade import CtpTradeData
from bt_api_ctp.ctp import client as ctp_client
from bt_api_ctp.ctp.ctp_structs_order import (
    CThostFtdcInputOrderActionField,
    CThostFtdcInputOrderField,
)
from bt_api_ctp.ctp_env_selector import (
    official_simnow_fronts,
    select_ctp_environment,
    select_reachable_ctp_environment,
    verify_official_simnow_profile,
)
from bt_api_ctp.exchange_data import CtpExchangeDataFuture
from bt_api_ctp.feeds.base_stream import BaseDataStream, ConnectionState
from bt_api_ctp.instrument import (
    build_ctp_instrument_spec,
    ctp_instrument_evidence_errors,
    ctp_query_bundle_errors,
)
from bt_api_ctp.query import QueryResult


def _is_exact_ctp_order_ref(value: Any) -> bool:
    return type(value) is str and len(value) == 12 and value.isascii() and value.isdecimal()


_CTP_MANAGED_QUOTE_V2_RECEIPT_SEAL = object()


@dataclass(frozen=True)
class _CtpManagedQuoteV2Receipt:
    """Opaque proof that one row came from a live native MD callback.

    The receipt deliberately contains no configurable qualification facts.
    CTP's raw market-data callback cannot prove clock calibration, freshness,
    or a rule-set identity, so configuration and subscription topics remain
    diagnostic only.  A future native evidence authority may extend this
    private contract; until then, ``execution_qualified`` remains false.
    """

    _seal: object
    _stream: Any
    _stream_token: object
    _ticker: CtpTickerData
    symbol: str
    connection_generation: int
    subscription_epoch: int
    ingest_seq: int
    source: str
    rules_hash: str
    clock_domain_id: str
    source_clock_quality: str
    receive_clock_quality: str
    source_clock_error_ms: float | None
    receive_clock_error_ms: float | None
    freshness_verified: bool
    execution_qualified: bool


def _get_ctp_managed_quote_v2_receipt(
    ticker: Any,
    stream: Any,
) -> dict[str, Any] | None:
    """Return a native-only V2 receipt bound to its ticker and live stream.

    This is an internal parent-SDK bridge.  It intentionally rejects a
    hand-built ``CtpTickerData``, a copied receipt, a stream replacement, and
    stale generation/subscription state.  It does not expose a way for public
    ``exchange_kwargs`` or subscription topics to manufacture qualification.
    """

    if type(ticker) is not CtpTickerData or type(stream) is not CtpMarketStream:
        return None
    receipt = getattr(ticker, "_managed_quote_v2_receipt", None)
    if (
        type(receipt) is not _CtpManagedQuoteV2Receipt
        or receipt._seal is not _CTP_MANAGED_QUOTE_V2_RECEIPT_SEAL
        or receipt._ticker is not ticker
        or receipt._stream is not stream
        or receipt._stream_token is not getattr(stream, "_managed_quote_v2_stream_token", None)
    ):
        return None
    try:
        stream_generation = int(getattr(stream, "_connection_generation", 0) or 0)
        stream_epoch = int(getattr(stream, "_subscription_epoch", 0) or 0)
        ticker_generation = int(getattr(ticker, "connection_generation", 0) or 0)
        ticker_epoch = int(getattr(ticker, "subscription_epoch", 0) or 0)
        ticker_seq = int(getattr(ticker, "ingest_seq", 0) or 0)
    except (TypeError, ValueError):
        return None
    symbol = str(ticker.get_symbol_name() or "").strip()
    if not (
        symbol
        and receipt.symbol == symbol
        and receipt.connection_generation > 0
        and receipt.connection_generation == stream_generation == ticker_generation
        and receipt.subscription_epoch > 0
        and receipt.subscription_epoch == stream_epoch == ticker_epoch
        and receipt.ingest_seq > 0
        and receipt.ingest_seq == ticker_seq
    ):
        return None
    return {
        "symbol": receipt.symbol,
        "connection_generation": receipt.connection_generation,
        "subscription_epoch": receipt.subscription_epoch,
        "ingest_seq": receipt.ingest_seq,
        "source": receipt.source,
        "rules_hash": receipt.rules_hash,
        "clock_domain_id": receipt.clock_domain_id,
        "source_clock_quality": receipt.source_clock_quality,
        "receive_clock_quality": receipt.receive_clock_quality,
        "source_clock_error_ms": receipt.source_clock_error_ms,
        "receive_clock_error_ms": receipt.receive_clock_error_ms,
        "freshness_verified": receipt.freshness_verified,
        "execution_qualified": receipt.execution_qualified,
    }


CTP_OFFSET_FLAG = {
    "open": "0",
    "close": "1",
    "force_close": "2",
    "close_today": "3",
    "close_yesterday": "4",
    "force_close_yesterday": "5",
    "local_force_close": "6",
}
CTP_DIRECTION_FLAG = {"buy": "0", "sell": "1"}
_ctp_field_logger = get_logger("ctp_field_converter")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _query_evidence(result: QueryResult[Any]) -> dict[str, Any]:
    evidence = result.as_dict(include_records=False)
    return {
        "query_result": evidence,
        "query_complete": result.complete,
        "evidence_complete": result.complete,
        "query_request_id": result.request_id,
        "query_connection_generation": result.connection_generation,
        "query_is_last_seen": result.is_last_seen,
        "query_error_code": result.error_code,
        "query_error_message": result.error_message,
        "query_timed_out": result.timed_out,
        "query_unsupported": result.unsupported,
    }


def _positive_int_lot(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"CTP order {field_name} must be a positive integer lot.")
    try:
        lot = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"CTP order {field_name} must be a positive integer lot.") from exc
    if not lot.is_finite() or lot <= 0 or lot != lot.to_integral_value():
        raise ValueError(f"CTP order {field_name} must be a positive integer lot.")
    return int(lot)


_CTP_INVALID_FLOAT_THRESHOLD = Decimal(str(float_info.max)) / 2
_CTP_QUOTE_INVALID_FLOAT_THRESHOLD = float_info.max / 2


def _positive_ctp_price(value: Any, field_name: str = "price") -> float:
    """Reject non-finite values and CTP's DBL_MAX missing-value sentinel."""
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"CTP order {field_name} must be a positive price with a finite value.")
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"CTP order {field_name} must be a positive price with a finite value."
        ) from exc
    if not price.is_finite() or price <= 0 or abs(price) >= _CTP_INVALID_FLOAT_THRESHOLD:
        raise ValueError(f"CTP order {field_name} must be a positive price with a finite value.")
    return float(price)


def _append_quote_quality_flag(row: CtpTickerData, flag: str) -> None:
    if flag not in row.quality_flags:
        row.quality_flags.append(flag)


def _valid_ctp_quote_number(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or value in (None, ""):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not isfinite(number) or abs(number) >= _CTP_QUOTE_INVALID_FLOAT_THRESHOLD:
        return False
    return number > 0 if positive else number >= 0


def _raw_quote_value(row: CtpTickerData, field_name: str, fallback: Any) -> Any:
    raw = getattr(row, "ticker_info", None)
    if isinstance(raw, dict):
        return raw.get(field_name)
    return fallback


def _validate_ctp_quote(row: CtpTickerData) -> bool:
    """Flag malformed required fields before they can update trusted state."""
    row.init_data()
    valid = True
    for field_name, raw_name, value in (
        ("LAST_PRICE", "LastPrice", row.get_last_price()),
        ("BID_PRICE", "BidPrice1", row.get_bid_price()),
        ("ASK_PRICE", "AskPrice1", row.get_ask_price()),
    ):
        if not _valid_ctp_quote_number(_raw_quote_value(row, raw_name, value), positive=True):
            _append_quote_quality_flag(row, f"INVALID_{field_name}")
            valid = False
    for field_name, raw_name, value in (
        ("BID_VOLUME", "BidVolume1", row.get_bid_volume()),
        ("ASK_VOLUME", "AskVolume1", row.get_ask_volume()),
        ("CUM_VOLUME", "Volume", row.get_cumulative_volume()),
        ("OPEN_INTEREST", "OpenInterest", row.get_open_interest()),
    ):
        if not _valid_ctp_quote_number(_raw_quote_value(row, raw_name, value)):
            _append_quote_quality_flag(row, f"INVALID_{field_name}")
            valid = False
    bid = row.get_bid_price()
    ask = row.get_ask_price()
    if _valid_ctp_quote_number(bid, positive=True) and _valid_ctp_quote_number(ask, positive=True):
        if float(bid) > float(ask):
            _append_quote_quality_flag(row, "CROSSED_BOOK")
            valid = False
        elif float(bid) == float(ask):
            _append_quote_quality_flag(row, "LOCKED_BOOK")
    if row.get_bid_volume() == 0 or row.get_ask_volume() == 0:
        _append_quote_quality_flag(row, "ZERO_DEPTH")
    return valid


def _safe_ctp_quote_number(value: Any) -> float:
    """Return a finite transport value while retaining invalidity in quality flags."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(number) or abs(number) >= _CTP_QUOTE_INVALID_FLOAT_THRESHOLD:
        return 0.0
    return number


def _resolve_ctp_runtime_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], str]:
    resolved = dict(kwargs)
    broker_id = str(resolved.get("broker_id") or os.environ.get("CTP_BROKER_ID") or "").strip()
    user_id = str(
        resolved.get("user_id")
        or resolved.get("investor_id")
        or os.environ.get("CTP_USER_ID")
        or ""
    ).strip()
    password = str(resolved.get("password") or os.environ.get("CTP_PASSWORD") or "").strip()
    auth_code = str(
        resolved.get("auth_code") or os.environ.get("CTP_AUTH_CODE") or "0000000000000000"
    ).strip()
    app_id = str(
        resolved.get("app_id") or os.environ.get("CTP_APP_ID") or "simnow_client_test"
    ).strip()
    td_front = str(resolved.get("td_front") or resolved.get("td_address") or "").strip()
    md_front = str(resolved.get("md_front") or resolved.get("md_address") or "").strip()
    static_td = str(os.environ.get("CTP_TD_FRONT") or "").strip()
    static_md = str(os.environ.get("CTP_MD_FRONT") or "").strip()
    had_partial_explicit_front = bool(td_front) != bool(md_front)
    claimed_profile = (
        str(
            resolved.get("ctp_env_profile")
            or resolved.get("ctp_profile")
            or os.environ.get("CTP_ENV_PROFILE")
            or ""
        )
        .strip()
        .lower()
    )
    auto_detect_fronts = _as_bool(resolved.get("auto_detect_fronts"), default=False)
    supplied_td = td_front or static_td
    supplied_md = md_front or static_md
    if claimed_profile and not auto_detect_fronts and bool(supplied_td) != bool(supplied_md):
        raise ValueError("claimed CTP profile requires both td_front and md_front, or neither")
    required_profile = (
        str(resolved.get("require_ctp_profile") or resolved.get("ctp_required_profile") or "")
        .strip()
        .lower()
    )
    if required_profile and (td_front or md_front) and not claimed_profile:
        raise RuntimeError(
            "required CTP profile cannot be proven from explicit fronts without ctp_env_profile"
        )
    if claimed_profile and required_profile:
        required_matches = (
            claimed_profile == required_profile
            or (required_profile == "set1" and claimed_profile.startswith("set1_"))
            or (required_profile == "set2" and claimed_profile.startswith("set2_"))
        )
        if not required_matches:
            raise RuntimeError(
                f"required CTP profile {required_profile!r}, configured {claimed_profile!r}"
            )
    front_probe_timeout = resolved.get("front_probe_timeout", 3.0)
    env_name = ""
    selected_environment = "custom"
    env_readiness = "explicit_front_override" if td_front and md_front else "unknown"
    auto_detected_selection = False
    if auto_detect_fronts:
        if bool(td_front) != bool(md_front):
            raise ValueError("auto-detected CTP front override requires both td_front and md_front")
        if not td_front and not md_front:
            # Process-wide CTP_TD/MD variables are compatibility state, not a
            # per-call override. Re-probe from the frozen profile family so a
            # pair selected before a VPN/network change cannot silently win.
            selection = select_reachable_ctp_environment(
                str(resolved.get("ctp_env") or ""),
                profile=claimed_profile or None,
                require_profile=required_profile or None,
                front_probe_timeout=front_probe_timeout,
            )
            td_front = selection.td_front
            md_front = selection.md_front
            claimed_profile = selection.profile
            env_name = selection.profile
            env_readiness = selection.readiness
            selected_environment = selection.environment
            auto_detected_selection = True
    elif claimed_profile and not td_front and not md_front and static_td and static_md:
        td_front, md_front = static_td, static_md
    elif claimed_profile and not td_front and not md_front:
        td_front, md_front = official_simnow_fronts(claimed_profile)

    if not td_front or not md_front:
        if os.environ.get("CTP_ENV") or not static_td or not static_md:
            selection = select_ctp_environment(require_profile=required_profile)
            td_front = td_front or selection.td_front
            md_front = md_front or selection.md_front
            env_name = selection.profile
            env_readiness = selection.readiness
            selected_environment = selection.environment
        else:
            td_front = td_front or static_td
            md_front = md_front or static_md
            env_name = "custom_front_override"
            env_readiness = "explicit_front_override"
        if had_partial_explicit_front:
            env_name = "mixed_front_override"
            env_readiness = "mixed_front_unverified"
            selected_environment = "custom"
    elif claimed_profile:
        if not verify_official_simnow_profile(td_front, md_front, claimed_profile):
            raise ValueError(
                f"claimed CTP profile {claimed_profile!r} does not match its official fronts"
            )
        env_name = claimed_profile
        env_readiness = (
            "tcp_pair_reachable" if auto_detected_selection else "explicit_official_pair"
        )
        selected_environment = "simnow"
    else:
        env_name = "custom_front_override"
    resolved.update(
        {
            "broker_id": broker_id,
            "user_id": user_id,
            "password": password,
            "auth_code": auth_code,
            "app_id": app_id,
            "td_front": td_front,
            "md_front": md_front,
            "ctp_environment": selected_environment,
            "ctp_env_profile": env_name,
            "ctp_env_readiness": env_readiness,
        }
    )
    return resolved, env_name


def _sanitize_ctp_field_value(value):
    if isinstance(value, str):
        return value.encode("gbk", errors="ignore").decode("gbk", errors="ignore")
    return value


def _ctp_field_to_dict(field):
    if field is None:
        return {}
    result = {}
    for attr in dir(field):
        if attr.startswith("_") or attr in {"this", "thisown"}:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UnicodeWarning)
                value = getattr(field, attr)
            if not callable(value):
                result[attr] = _sanitize_ctp_field_value(value)
        except Exception as exc:
            _ctp_field_logger.debug(
                f"Failed to access CTP field attribute '{attr}': {exc}", exc_info=False
            )
    return result


class CtpVolumeDeltaTracker:
    """The single SDK authority for CTP cumulative-volume conversion."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], dict[str, Any]] = {}

    def apply(self, row: CtpTickerData) -> CtpTickerData:
        row.init_data()
        instrument = row.get_symbol_name() or ""
        key = (str(row.exchange_id or ""), instrument)
        total = float(row.get_cumulative_volume() or 0.0)
        scope = (
            int(row.connection_generation or 0),
            int(getattr(row, "subscription_epoch", 0) or 0),
            str(row.trading_day or ""),
        )
        previous = self._state.get(key)
        delta = 0.0
        complete = False
        quality = "BASELINE"
        if previous is not None:
            if previous["scope"] != scope:
                quality = "CONNECTION_OR_TRADING_DAY_RESET"
            elif row.ingest_seq and row.ingest_seq <= previous["ingest_seq"]:
                quality = "OUT_OF_ORDER"
                row.quality_flags.append("OUT_OF_ORDER")
            elif total < previous["cum_volume"]:
                quality = "VOLUME_RESET"
                row.quality_flags.append("VOLUME_GAP")
            else:
                delta = total - previous["cum_volume"]
                complete = True
                quality = "CONTINUOUS"
        if quality != "OUT_OF_ORDER":
            self._state[key] = {
                "scope": scope,
                "cum_volume": total,
                "ingest_seq": int(row.ingest_seq or 0),
            }
        return row.apply_volume_delta(delta, complete=complete, quality=quality)


class CtpRequestData(Feed):
    @classmethod
    def _capabilities(cls):
        return {
            Capability.GET_TICK,
            Capability.MAKE_ORDER,
            Capability.CANCEL_ORDER,
            Capability.QUERY_ORDER,
            Capability.QUERY_OPEN_ORDERS,
            Capability.GET_DEALS,
            Capability.GET_BALANCE,
            Capability.GET_ACCOUNT,
            Capability.GET_POSITION,
            Capability.GET_EXCHANGE_INFO,
            Capability.MARKET_STREAM,
            Capability.ACCOUNT_STREAM,
        }

    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        super().__init__(data_queue)
        resolved_kwargs, self.ctp_env_name = _resolve_ctp_runtime_kwargs(kwargs)
        self.ctp_env_profile = resolved_kwargs.get("ctp_env_profile", self.ctp_env_name)
        self.ctp_env_readiness = resolved_kwargs.get("ctp_env_readiness", "unknown")
        self.ctp_environment = resolved_kwargs.get("ctp_environment", "custom")
        self.data_queue = data_queue
        self.broker_id = resolved_kwargs.get("broker_id", "")
        self.user_id = resolved_kwargs.get("user_id", "")
        self.password = resolved_kwargs.get("password", "")
        self.auth_code = resolved_kwargs.get("auth_code", "0000000000000000")
        self.app_id = resolved_kwargs.get("app_id", "simnow_client_test")
        self.td_front = resolved_kwargs.get("td_front", "")
        self.md_front = resolved_kwargs.get("md_front", "")
        # The feed exposes these legacy attributes for inspection, but the
        # managed execution boundary binds the original account/front/profile.
        # A later public mutation must not turn an authenticated TraderClient
        # into a differently routed native write session.
        self._execution_bound_broker_id = str(self.broker_id or "").strip()
        self._execution_bound_user_id = str(self.user_id or "").strip()
        self._execution_bound_td_front = str(self.td_front or "").strip()
        self._execution_bound_md_front = str(self.md_front or "").strip()
        self._execution_bound_environment = str(self.ctp_environment or "").strip()
        self._execution_bound_profile = str(self.ctp_env_profile or "").strip()
        self.asset_type = resolved_kwargs.get("asset_type", "FUTURE")
        self.exchange_name = "CTP"
        self._params = CtpExchangeDataFuture()
        self.request_logger = get_logger("ctp_feed")
        self._trader = None
        self._connect_lock = threading.Lock()
        self._connected = False
        self._connect_timeout = resolved_kwargs.get("connect_timeout", 15)
        self._execution_gate_capability: object | None = None
        self.auto_settlement_confirm = _as_bool(
            resolved_kwargs.get("auto_settlement_confirm"), default=False
        )

    def translate_error(self, raw_response):
        if isinstance(raw_response, dict) and raw_response.get("ErrorID", 0) != 0:
            return raw_response
        return None

    def _ensure_read_only_connection_safe(self) -> None:
        """Refuse a session configuration that can write during read-only use.

        CTP's settlement-confirm call is a terminal write.  Account, position,
        instrument and option-cost preflight queries must not create a client
        that can send it automatically, nor reuse an already-connected client
        carrying that unsafe setting.
        """

        if self.auto_settlement_confirm is not False:
            raise ctp_client.CtpExecutionGateError(
                "ctp_execution_gate_auto_settlement_confirm_enabled"
            )
        trader = self._trader
        if trader is not None and getattr(trader, "auto_settlement_confirm", None) is not False:
            raise ctp_client.CtpExecutionGateError(
                "ctp_execution_gate_auto_settlement_confirm_enabled"
            )

    def configure_execution_gate(self, capability: object) -> dict[str, Any]:
        """Install the SDK-owned gate without changing legacy feed behavior."""

        if not ctp_client._is_ctp_core_execution_authority(capability):
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_required")
        with self._connect_lock:
            self._ensure_read_only_connection_safe()
            installed = self._execution_gate_capability
            if installed is not None and installed is not capability:
                raise ctp_client.CtpExecutionGateError("ctp_execution_gate_already_configured")
            self._execution_gate_capability = capability
            trader = self._trader
            if trader is not None:
                method = getattr(trader, "configure_execution_gate", None)
                if not callable(method):
                    raise ctp_client.CtpExecutionGateError(
                        "ctp_execution_gate_native_contract_unavailable"
                    )
                return dict(method(capability))
        return self.get_execution_gate_state()

    def _issue_execution_capability_for_core(self) -> object:
        """Return the private capability consumed by the parent SDK only.

        It is intentionally underscored so a normal direct-feed caller cannot
        turn an arbitrary ``object()`` into a write capability.  The native
        client independently verifies its exact type and issuer seal.
        """

        return ctp_client._issue_ctp_execution_authority_for_core()

    def _execution_environment_proof(self) -> dict[str, Any]:
        """Return a provider-verified environment binding or fail closed."""

        info = self.get_environment_info()
        profile = self._execution_bound_profile
        if (
            not isinstance(info, dict)
            or info.get("verified") is not True
            or info.get("environment") != "demo"
            or str(info.get("profile") or "").strip() != profile
            or not profile
        ):
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_environment_unverified")
        trader = self._trader
        identity_is_current = getattr(trader, "_bound_identity_is_current", None)
        if (
            trader is None
            or str(getattr(trader, "_bound_front", "") or "") != self._execution_bound_td_front
            or str(getattr(trader, "_bound_broker_id", "") or "") != self._execution_bound_broker_id
            or str(getattr(trader, "_bound_user_id", "") or "") != self._execution_bound_user_id
            or str(getattr(trader, "_session_native_front", "") or "")
            != self._execution_bound_td_front
            or not callable(identity_is_current)
            or identity_is_current(require_active_front=True) is not True
        ):
            raise ctp_client.CtpExecutionGateError(
                "ctp_execution_gate_environment_binding_mismatch"
            )
        return {
            "environment_profile": profile,
            "environment_verified": True,
        }

    def _issue_execution_authorization_for_core(
        self,
        capability: object,
        proof: Any,
        *,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
    ) -> object:
        """Private mapping-to-token bridge used only by the owning SDK."""

        with self._connect_lock:
            if capability is not self._execution_gate_capability:
                raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            environment = self._execution_environment_proof()
            trader = self._trader
            method = getattr(trader, "_issue_execution_authorization_for_core", None)
            if trader is None or not callable(method):
                raise ctp_client.CtpExecutionGateError(
                    "ctp_execution_gate_native_contract_unavailable"
                )
            return method(
                capability,
                proof,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                **environment,
            )

    def _issue_settlement_authorization_for_core(
        self,
        capability: object,
    ) -> object:
        """Private, independent one-shot settlement-confirm issuer."""

        with self._connect_lock:
            if capability is not self._execution_gate_capability:
                raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            environment = self._execution_environment_proof()
            trader = self._trader
            method = getattr(trader, "_issue_settlement_authorization_for_core", None)
            if trader is None or not callable(method):
                raise ctp_client.CtpExecutionGateError(
                    "ctp_execution_gate_native_contract_unavailable"
                )
            return method(capability, **environment)

    def arm_execution_gate(
        self,
        capability: object,
        authorization: object,
    ) -> dict[str, Any]:
        """Consume a native one-shot arm authorization.

        Mapping proofs are deliberately not accepted at this public feed
        boundary, even if they were reconstructed from public session state.
        """

        with self._connect_lock:
            if capability is not self._execution_gate_capability:
                raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            trader = self._trader
            method = getattr(trader, "arm_execution_gate", None)
            if trader is None or not callable(method):
                raise ctp_client.CtpExecutionGateError(
                    "ctp_execution_gate_native_contract_unavailable"
                )
            # The provider/front binding is revalidated at consumption, not
            # only when the parent issued the opaque grant.  This blocks a
            # post-preflight custom profile or reconnect drift before native
            # order writes can become armed.
            environment = self._execution_environment_proof()
            return dict(
                method(
                    capability,
                    authorization,
                    _environment_profile=environment["environment_profile"],
                    _environment_verified=environment["environment_verified"],
                )
            )

    def disarm_execution_gate(
        self,
        capability: object,
        reason: str = "execution_arm_revoked",
    ) -> dict[str, Any]:
        """Idempotently revoke managed writes while retaining read access."""

        with self._connect_lock:
            if capability is not self._execution_gate_capability:
                raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            trader = self._trader
            if trader is None:
                return self.get_execution_gate_state()
            method = getattr(trader, "disarm_execution_gate", None)
            if not callable(method):
                raise ctp_client.CtpExecutionGateError(
                    "ctp_execution_gate_native_contract_unavailable"
                )
            return dict(method(capability, reason))

    def get_execution_gate_state(self) -> dict[str, Any]:
        """Return gate evidence without returning its opaque capability."""

        trader = self._trader
        method = getattr(trader, "get_execution_gate_state", None)
        if callable(method):
            return dict(method())
        return {
            "managed": self._execution_gate_capability is not None,
            "armed": False,
            "connection_generation": None,
            "trading_day": None,
            "instrument": None,
            "scope_version": None,
            "authorized_instruments": None,
            "environment_profile": None,
            "proof_sha256": None,
            "revocation_reason": None,
        }

    def _ensure_execution_permitted(
        self,
        capability: object | None,
        symbol: Any,
        exchange_id: Any = None,
    ) -> None:
        installed = self._execution_gate_capability
        if installed is None:
            # A CTP request feed may stay connected for read-only discovery,
            # but it must never retain the former unguarded order path.  The
            # opaque capability is installed only by the owning SDK execution
            # session before an arming proof is accepted.
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_required")
        if capability is not installed:
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
        trader = self._trader
        method = getattr(trader, "require_execution_write", None)
        state_reader = getattr(trader, "get_execution_gate_state", None)
        if trader is None or not callable(method) or not callable(state_reader):
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        state = state_reader()
        if not isinstance(state, dict) or state.get("managed") is not True:
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        if state.get("armed") is not True:
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_unarmed")
        method(capability, symbol, exchange_id)

    def _ensure_settlement_confirmation_permitted(
        self,
        capability: object | None,
        settlement_authorization: object | None,
    ) -> tuple[object, dict[str, Any]]:
        """Require a distinct core-owned one-shot settlement authorization.

        Settlement confirmation must happen before an order proof can be
        armed, so it deliberately requires a managed *disarmed* gate rather
        than an already armed order scope.  This keeps query-only sessions
        usable while preventing the former implicit terminal write.
        """

        installed = self._execution_gate_capability
        if installed is None or not ctp_client._is_ctp_core_execution_authority(installed):
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_required")
        if capability is not installed:
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
        trader = self._trader
        method = getattr(trader, "confirm_settlement", None)
        state_reader = getattr(trader, "get_execution_gate_state", None)
        if trader is None or not callable(method) or not callable(state_reader):
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        state = state_reader()
        if not isinstance(state, dict) or state.get("managed") is not True:
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        if state.get("armed") is not False:
            raise ctp_client.CtpExecutionGateError(
                "ctp_execution_gate_settlement_requires_disarmed"
            )
        if settlement_authorization is None or isinstance(settlement_authorization, Mapping):
            raise ctp_client.CtpExecutionGateError("ctp_settlement_authorization_required")
        # Re-read the provider-verified front/profile at consumption time, not
        # only when the token was issued.  A mutable feed/client attribute or
        # reconnect must not make a previously valid settlement grant usable
        # against a different native session.
        environment = self._execution_environment_proof()
        # Native TraderClient validates the opaque token's account/day/
        # generation/scope/budget and the verified profile immediately before
        # ReqSettlementInfoConfirm.  Do not attempt to turn a mapping or the
        # installed capability into a substitute at the feed layer.
        return settlement_authorization, environment

    def _ensure_connected(self):
        self._ensure_read_only_connection_safe()
        if self._trader is None or not self._trader.is_read_only_ready:
            self.connect()
        if not self._trader or not self._trader.is_read_only_ready:
            raise BtConnectionError("CTP", "TraderClient not read-only ready after connect()")

    def _ensure_trading_ready(self):
        self._ensure_connected()
        if not self._trader or not self._trader.is_trading_ready:
            raise BtConnectionError(
                "CTP",
                "TraderClient settlement is unconfirmed; order writes are disabled",
            )

    def connect(self):
        with self._connect_lock:
            self._ensure_read_only_connection_safe()
            trader = self._trader
            if trader is None:
                trader = ctp_client.TraderClient(
                    self._execution_bound_td_front,
                    self._execution_bound_broker_id,
                    self._execution_bound_user_id,
                    self.password,
                    app_id=self.app_id,
                    auth_code=self.auth_code,
                    auto_settlement_confirm=self.auto_settlement_confirm,
                )
                if self._execution_gate_capability is not None:
                    trader.configure_execution_gate(self._execution_gate_capability)
                self._trader = trader
                trader.start(block=False)
            if getattr(trader, "is_read_only_ready", False):
                self._connected = True
                return
            wait_ready = getattr(trader, "wait_ready", None)
            self._connected = bool(
                callable(wait_ready) and wait_ready(timeout=self._connect_timeout)
            )

    def disconnect(self):
        with self._connect_lock:
            trader = self._trader
            self._trader = None
            capability = self._execution_gate_capability
        if trader is not None:
            if capability is not None:
                with suppress(Exception):
                    trader.disarm_execution_gate(capability, "ctp_execution_gate_feed_disconnected")
            trader.stop()
        self._connected = False

    def _make_request_data(
        self, data_list, request_type, symbol_name=None, extra_data=None, status=True
    ):
        payload = extra_data.copy() if extra_data else {}
        payload.setdefault("exchange_name", self.exchange_name)
        payload.setdefault("symbol_name", symbol_name or "")
        payload.setdefault("asset_type", self.asset_type)
        payload.setdefault("request_type", request_type)
        request = RequestData(data_list, payload, status=status)
        request.data = data_list
        request.has_been_init_data = True
        return request

    def get_account(self, symbol=None, extra_data=None, **kwargs):
        self._ensure_connected()
        trader = self._trader
        if trader is None:
            return self._make_request_data([], "get_account", symbol, extra_data, status=False)
        result = trader.query_account_result(timeout=kwargs.get("timeout", 5))
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = [
            CtpAccountData(_ctp_field_to_dict(raw), symbol, self.asset_type, True)
            for raw in result.records
        ]
        snapshot_complete = result.complete and len(rows) == 1
        payload["account_snapshot_complete"] = snapshot_complete
        if result.complete and not rows:
            payload["account_snapshot_error"] = "complete_query_returned_no_account"
        elif result.complete and len(rows) > 1:
            payload["account_snapshot_error"] = "complete_query_returned_multiple_accounts"
        return self._make_request_data(
            rows if snapshot_complete else [],
            "get_account",
            symbol,
            payload,
            status=snapshot_complete,
        )

    def get_balance(self, symbol=None, extra_data=None, **kwargs):
        return self.get_account(symbol, extra_data, **kwargs)

    def get_position(self, symbol=None, extra_data=None, **kwargs):
        self._ensure_connected()
        trader = self._trader
        if trader is None:
            return self._make_request_data([], "get_position", symbol, extra_data, status=False)
        result = trader.query_positions_result(timeout=kwargs.get("timeout", 5))
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = []
        for raw in result.records:
            data = _ctp_field_to_dict(raw)
            rows.append(
                CtpPositionData(data, data.get("InstrumentID", symbol), self.asset_type, True)
            )
        return self._make_request_data(
            rows if result.complete else [],
            "get_position",
            symbol,
            payload,
            status=result.complete,
        )

    def get_tick(self, symbol, extra_data=None, **kwargs):
        return self._make_request_data([], "get_tick", symbol, extra_data, status=False)

    def get_depth(self, symbol, count=5, extra_data=None, **kwargs):
        return self._make_request_data([], "get_depth", symbol, extra_data, status=False)

    def get_kline(self, symbol, period, count=100, extra_data=None, **kwargs):
        return self._make_request_data([], "get_kline", symbol, extra_data, status=False)

    def make_order(
        self,
        symbol,
        volume,
        price=None,
        order_type="buy-limit",
        offset="open",
        post_only=False,
        client_order_id=None,
        extra_data=None,
        **kwargs,
    ):
        execution_capability = kwargs.pop("_execution_capability", None)
        exchange_id = kwargs.get("exchange_id", "")
        self._ensure_execution_permitted(execution_capability, symbol, exchange_id)
        if not _is_exact_ctp_order_ref(client_order_id):
            raise ValueError(
                "managed CTP orders require an exact 12-digit ASCII client_order_id"
            )
        self._ensure_trading_ready()
        trader = self._trader
        if trader is None:
            return self._make_request_data([], "make_order", symbol, extra_data, status=False)
        self._ensure_execution_permitted(execution_capability, symbol, exchange_id)
        try:
            side, order_kind = str(order_type or "").lower().split("-", 1)
        except ValueError as exc:
            raise ValueError(
                f"CTP order_type must be '<buy|sell>-limit' (got {order_type!r})."
            ) from exc
        if side not in CTP_DIRECTION_FLAG:
            raise ValueError(f"CTP order side must be buy or sell (got {side!r}).")
        if order_kind != "limit":
            raise ValueError(
                f"CTP order kind {order_kind!r} is unsupported; use a positive-price limit order."
            )
        offset_text = str(offset or "open").lower()
        if offset_text not in CTP_OFFSET_FLAG:
            raise ValueError(f"CTP order offset {offset!r} is unsupported.")
        order_volume = _positive_int_lot(volume, "volume")
        direction = CTP_DIRECTION_FLAG[side]
        offset_flag = CTP_OFFSET_FLAG[offset_text]
        field = CThostFtdcInputOrderField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        field.UserID = self.user_id
        field.InstrumentID = symbol
        if exchange_id:
            field.ExchangeID = exchange_id
        field.Direction = direction
        field.CombOffsetFlag = offset_flag
        field.CombHedgeFlag = "1"
        field.VolumeTotalOriginal = order_volume
        field.MinVolume = 1
        field.ForceCloseReason = "0"
        field.IsAutoSuspend = 0
        field.UserForceClose = 0
        field.ContingentCondition = "1"
        limit_price = _positive_ctp_price(price)
        field.OrderPriceType = "2"
        field.TimeCondition = "3"
        field.VolumeCondition = "1"
        time_in_force = str(kwargs.get("time_in_force") or kwargs.get("tif") or "GFD").upper()
        if time_in_force == "DAY":
            time_in_force = "GFD"
        if time_in_force != "GFD":
            raise ValueError(
                f"CTP time_in_force {time_in_force!r} is unsupported; iteration 22 requires GFD."
            )
        field.LimitPrice = limit_price
        field.OrderRef = client_order_id
        next_req_id = trader._next_request_id()
        field.RequestID = next_req_id
        submit = getattr(trader, "submit_order_insert", None)
        if callable(submit):
            ret = submit(
                field,
                next_req_id,
                execution_capability=execution_capability,
            )
        else:
            # Do not preserve a raw ``ReqOrderInsert`` compatibility fallback:
            # it would bypass the locked final gate in ``TraderClient`` after
            # the feed has validated its initial authorization.
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        order_dict = _ctp_field_to_dict(field)
        order_dict["_ret"] = ret
        order_dict["FrontID"] = getattr(trader, "_front_id", 0)
        order_dict["SessionID"] = getattr(trader, "_session_id", 0)
        if ret != 0:
            return self._make_request_data([], "make_order", symbol, extra_data, status=False)
        return self._make_request_data(
            [CtpOrderData(order_dict, symbol, self.asset_type, True)],
            "make_order",
            symbol,
            extra_data,
        )

    def cancel_order(self, symbol, order_id=None, extra_data=None, **kwargs):
        execution_capability = kwargs.pop("_execution_capability", None)
        exchange_id = kwargs.get("exchange_id", "")
        runtime_order_id = kwargs.get("runtime_order_id")
        managed_intent_id = kwargs.get("managed_intent_id")
        runtime_action_id = kwargs.get("runtime_action_id")
        managed_cancel_intent_id = kwargs.get("managed_cancel_intent_id")
        managed_cancel = ctp_client._validate_managed_cancel_identity(
            runtime_order_id=runtime_order_id,
            managed_intent_id=managed_intent_id,
            runtime_action_id=runtime_action_id,
            managed_cancel_intent_id=managed_cancel_intent_id,
        )
        order_ref = kwargs.get("order_ref", "")
        front_id = kwargs.get("front_id", 0)
        session_id = kwargs.get("session_id", 0)
        if managed_cancel:
            ctp_client._validate_managed_cancel_target_values(
                order_ref=order_ref,
                order_sys_id=order_id,
                exchange_id=exchange_id,
                front_id=front_id,
                session_id=session_id,
            )
        self._ensure_execution_permitted(execution_capability, symbol, exchange_id)
        self._ensure_trading_ready()
        trader = self._trader
        if trader is None:
            return self._make_request_data([], "cancel_order", symbol, extra_data, status=False)
        self._ensure_execution_permitted(execution_capability, symbol, exchange_id)
        field = CThostFtdcInputOrderActionField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        field.InstrumentID = symbol
        field.ActionFlag = "0"
        if exchange_id:
            field.ExchangeID = exchange_id
        if managed_cancel:
            field.UserID = self.user_id
            field.ExchangeID = exchange_id
            field.OrderRef = order_ref
            field.OrderSysID = order_id
            field.FrontID = front_id
            field.SessionID = session_id
        elif order_id:
            field.OrderSysID = str(order_id)
        if not managed_cancel and order_ref:
            field.OrderRef = str(order_ref)
            field.FrontID = int(front_id) if front_id else trader._front_id
            field.SessionID = int(session_id) if session_id else trader._session_id
        request_id = trader._next_request_id()
        field.RequestID = request_id
        field.OrderActionRef = request_id
        submit = getattr(trader, "submit_order_action", None)
        if callable(submit):
            submit_kwargs = {"execution_capability": execution_capability}
            if managed_cancel:
                submit_kwargs.update(
                    runtime_order_id=runtime_order_id,
                    managed_intent_id=managed_intent_id,
                    runtime_action_id=runtime_action_id,
                    managed_cancel_intent_id=managed_cancel_intent_id,
                )
            ret = submit(field, request_id, **submit_kwargs)
        else:
            # See the insert path above.  A cancellation is also a real CTP
            # write and must cross the typed, locked native gate.
            raise ctp_client.CtpExecutionGateError("ctp_execution_gate_native_contract_unavailable")
        return self._make_request_data(
            [_ctp_field_to_dict(field)],
            "cancel_order",
            symbol,
            extra_data,
            status=(ret == 0),
        )

    def query_order(self, symbol=None, order_id=None, extra_data=None, **kwargs):
        trader = self._trader
        if trader is None or not getattr(trader, "is_read_only_ready", False):
            return self._make_request_data([], "query_order", symbol, extra_data, status=False)
        result = trader.query_orders_result(
            instrument_id=symbol or "",
            exchange_id=kwargs.get("exchange_id", ""),
            order_sys_id=order_id or "",
            timeout=kwargs.get("timeout", 5),
        )
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = []
        for raw in result.records:
            data = raw if isinstance(raw, dict) else _ctp_field_to_dict(raw)
            # OrderRef is local to a front/session and is not an OrderSysID.
            # The native query filters OrderSysID; filter the alternative
            # client reference here before returning public order containers.
            if any(
                kwargs.get(key) is not None and str(data.get(native_key, "")) != str(kwargs[key])
                for key, native_key in (
                    ("order_ref", "OrderRef"),
                    ("front_id", "FrontID"),
                    ("session_id", "SessionID"),
                )
            ):
                continue
            rows.append(CtpOrderData(data, data.get("InstrumentID", symbol), self.asset_type, True))
        return self._make_request_data(
            rows if result.complete else [],
            "query_order",
            symbol,
            payload,
            status=result.complete,
        )

    def get_open_orders(self, symbol=None, extra_data=None, **kwargs):
        response = self.query_order(symbol=symbol, extra_data=extra_data, **kwargs)
        if not response.get_status():
            return self._make_request_data(
                [],
                "get_open_orders",
                symbol,
                response.get_extra_data(),
                status=False,
            )
        rows = []
        for row in response.get_data() or []:
            order = row.init_data()
            if order.get_order_status() in {
                OrderStatus.COMPLETED,
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
                OrderStatus.MMP_CANCELED,
                OrderStatus.EXPIRED_IN_MATCH,
            }:
                continue
            if int(order.volume_total or 0) > 0:
                rows.append(order)
        return self._make_request_data(rows, "get_open_orders", symbol, response.get_extra_data())

    def get_deals(
        self,
        symbol=None,
        count=100,
        start_time=None,
        end_time=None,
        extra_data=None,
        **kwargs,
    ):
        trader = self._trader
        if trader is None or not getattr(trader, "is_read_only_ready", False):
            return self._make_request_data([], "get_deals", symbol, extra_data, status=False)
        result = trader.query_trades_result(
            instrument_id=symbol or "",
            exchange_id=kwargs.get("exchange_id", ""),
            trade_id=kwargs.get("trade_id", ""),
            start_time=start_time or "",
            end_time=end_time or "",
            timeout=kwargs.get("timeout", 5),
        )
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = []
        for raw in result.records:
            data = raw if isinstance(raw, dict) else _ctp_field_to_dict(raw)
            rows.append(CtpTradeData(data, data.get("InstrumentID", symbol), self.asset_type, True))
        total_records = len(rows)
        truncated = False
        if count is not None:
            limit = max(int(count), 0)
            truncated = total_records > limit
            rows = rows[-limit:] if limit else []
        snapshot_complete = result.complete and not truncated
        payload.update(
            trade_snapshot_complete=snapshot_complete,
            trade_record_count=total_records,
            returned_trade_record_count=len(rows),
            records_truncated=truncated,
            evidence_complete=snapshot_complete,
        )
        return self._make_request_data(
            rows if snapshot_complete else [],
            "get_deals",
            symbol,
            payload,
            status=snapshot_complete,
        )

    def get_instruments(self, symbol=None, extra_data=None, **kwargs):
        self._ensure_connected()
        trader = self._trader
        if trader is None:
            return self._make_request_data([], "get_instruments", symbol, extra_data, status=False)
        query_kwargs = {
            "instrument_id": symbol or "",
            "exchange_id": kwargs.get("exchange_id", ""),
            "timeout": kwargs.get("timeout", 5),
        }
        product_id = kwargs.get("product_id", "")
        if product_id:
            query_kwargs["product_id"] = product_id
        result = trader.query_instruments_result(**query_kwargs)
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = [raw if isinstance(raw, dict) else _ctp_field_to_dict(raw) for raw in result.records]
        return self._make_request_data(
            rows if result.complete else [],
            "get_instruments",
            symbol,
            payload,
            status=result.complete,
        )

    def get_instrument_margin_rate(self, symbol, extra_data=None, **kwargs):
        self._ensure_connected()
        result = self._trader.query_instrument_margin_rate_result(
            symbol,
            exchange_id=kwargs.get("exchange_id", ""),
            hedge_flag=kwargs.get("hedge_flag", "1"),
            timeout=kwargs.get("timeout", 5),
        )
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = [raw if isinstance(raw, dict) else _ctp_field_to_dict(raw) for raw in result.records]
        return self._make_request_data(
            rows if result.complete else [],
            "get_instrument_margin_rate",
            symbol,
            payload,
            status=result.complete,
        )

    def get_instrument_commission_rate(self, symbol, extra_data=None, **kwargs):
        self._ensure_connected()
        result = self._trader.query_instrument_commission_rate_result(
            symbol,
            exchange_id=kwargs.get("exchange_id", ""),
            timeout=kwargs.get("timeout", 5),
        )
        payload = dict(extra_data or {})
        payload.update(_query_evidence(result))
        rows = [raw if isinstance(raw, dict) else _ctp_field_to_dict(raw) for raw in result.records]
        return self._make_request_data(
            rows if result.complete else [],
            "get_instrument_commission_rate",
            symbol,
            payload,
            status=result.complete,
        )

    def get_exchange_info(self, symbol=None, extra_data=None, **kwargs):
        """Bridge terminal instrument/margin/fee queries to one strict public spec."""
        if not symbol:
            response = self.get_instruments(symbol=None, extra_data=extra_data, **kwargs)
            payload = dict(response.get_extra_data() or {})
            payload.update(
                metadata_complete=False,
                metadata_evidence="instrument_enumeration_has_no_account_fee_or_margin_join",
            )
            records = []
            for raw in response.get_data() or []:
                record = dict(raw) if isinstance(raw, dict) else _ctp_field_to_dict(raw)
                record.update(metadata_complete=False, evidence_complete=False)
                records.append(record)
            return self._make_request_data(
                records,
                "get_exchange_info",
                symbol,
                payload,
                status=response.get_status(),
            )

        text = str(symbol).strip()
        exchange_id = str(kwargs.get("exchange_id") or "").strip().upper()
        instrument = text
        for separator in (".", "_"):
            if separator not in text:
                continue
            left, right = (part.strip() for part in text.split(separator, 1))
            if left.upper() in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}:
                exchange_id, instrument = left.upper(), right
            elif right.upper() in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}:
                instrument, exchange_id = left, right.upper()
            break

        timeout = kwargs.get("timeout", 5)
        hedge_flag = kwargs.get("hedge_flag", "1")
        instrument_result = self.query_instruments_result(
            instrument_id=instrument,
            exchange_id=exchange_id,
            timeout=timeout,
        )
        margin_result = self.query_instrument_margin_rate_result(
            instrument,
            exchange_id=exchange_id,
            hedge_flag=hedge_flag,
            timeout=timeout,
        )
        commission_result = self.query_instrument_commission_rate_result(
            instrument,
            exchange_id=exchange_id,
            timeout=timeout,
        )
        results = (instrument_result, margin_result, commission_result)
        payload = dict(extra_data or {})
        payload["component_queries"] = {
            result.request_type: result.as_dict(include_records=False) for result in results
        }
        record_complete = all(result.complete and len(result.records) == 1 for result in results)
        session_getter = getattr(self._trader, "get_session_state", None)
        current_session = session_getter() if callable(session_getter) else None
        bundle_errors = ctp_query_bundle_errors(results, current_session=current_session)
        if not record_complete or bundle_errors:
            payload["metadata_error"] = (
                "query_record_incomplete" if not record_complete else ",".join(bundle_errors)
            )
            payload.update(metadata_complete=False, evidence_complete=False)
            return self._make_request_data([], "get_exchange_info", text, payload, status=False)

        spec = build_ctp_instrument_spec(
            instrument,
            exchange_id,
            instrument_result.records[0],
            margin_result.records[0],
            commission_result.records[0],
        )
        evidence_errors = ctp_instrument_evidence_errors(
            instrument,
            exchange_id,
            instrument_result.records[0],
            margin_result.records[0],
            commission_result.records[0],
        )
        metadata_complete = not evidence_errors
        if evidence_errors:
            payload["metadata_error"] = ",".join(evidence_errors)
        spec.update(
            symbol=text,
            instrument=instrument,
            metadata_complete=metadata_complete,
            evidence_complete=metadata_complete,
        )
        payload.update(
            metadata_complete=metadata_complete,
            evidence_complete=metadata_complete,
        )
        return self._make_request_data(
            [spec] if metadata_complete else [],
            "get_exchange_info",
            text,
            payload,
            status=metadata_complete,
        )

    @property
    def trader_client(self):
        return self._trader

    def get_environment_info(self) -> dict[str, Any]:
        profile = str(self.ctp_env_profile or "").strip()
        binding_is_current = (
            profile == self._execution_bound_profile
            and str(self.ctp_environment or "").strip() == self._execution_bound_environment
            and str(self.td_front or "").strip() == self._execution_bound_td_front
            and str(self.md_front or "").strip() == self._execution_bound_md_front
            and str(self.broker_id or "").strip() == self._execution_bound_broker_id
            and str(self.user_id or "").strip() == self._execution_bound_user_id
        )
        official_simnow = bool(
            binding_is_current
            and self._execution_bound_environment == "simnow"
            and profile
            and verify_official_simnow_profile(
                self._execution_bound_td_front,
                self._execution_bound_md_front,
                profile,
            )
        )
        return {
            "environment": "demo" if official_simnow else "unknown",
            "simulated": True if official_simnow else None,
            "verified": official_simnow,
            "profile": profile,
            "readiness": self.ctp_env_readiness,
        }

    def get_session_state(self) -> dict[str, Any]:
        if self._trader is None:
            return {
                "connected": False,
                "auth_state": "disconnected",
                "login_state": "disconnected",
                "settlement_state": "unknown",
                "read_only_ready": False,
                "trading_ready": False,
                "settlement_readback_verified": False,
                "request_counts": ctp_client.empty_ctp_request_counts(),
                "environment_profile": self.ctp_env_profile,
                "environment_readiness": self.ctp_env_readiness,
            }
        result = self._trader.get_session_state()
        result.update(
            environment_profile=self.ctp_env_profile,
            environment_readiness=self.ctp_env_readiness,
        )
        return result

    def get_query_session_scope(self) -> Any:
        """Return the client's opaque scope for strict query evidence."""

        self._ensure_connected()
        trader = getattr(self, "_trader", None)
        method = getattr(trader, "get_query_session_scope", None)
        if trader is None or not callable(method):
            raise CtpPositionEvidenceError("position_session_scope_untrusted")
        return method()

    def get_request_counts(self) -> dict[str, int]:
        if self._trader is None:
            return ctp_client.empty_ctp_request_counts()
        return self._trader.get_request_counts()

    def confirm_settlement(
        self,
        timeout: float = 5.0,
        *,
        _execution_capability: object | None = None,
        _settlement_authorization: object | None = None,
    ) -> bool:
        with self._connect_lock:
            self._ensure_read_only_connection_safe()
            settlement_authorization, environment = self._ensure_settlement_confirmation_permitted(
                _execution_capability, _settlement_authorization
            )
            return bool(
                self._trader.confirm_settlement(
                    timeout=timeout,
                    _execution_capability=_execution_capability,
                    _settlement_authorization=settlement_authorization,
                    _settlement_environment_profile=environment["environment_profile"],
                    _settlement_environment_verified=environment["environment_verified"],
                )
            )

    def verify_settlement_confirmation(self, timeout: float = 5.0) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.verify_settlement_confirmation(timeout=timeout)

    def query_account_result(self, timeout: float = 5.0) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_account_result(timeout=timeout)

    def query_positions_result(self, timeout: float = 5.0) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_positions_result(timeout=timeout)

    def query_positions_evidence(
        self, timeout: float = 5.0, ttl_seconds: float = 5.0
    ) -> CtpPositionEvidence:
        """Return strict immutable evidence from the public positions query.

        The feed obtains the query and current session scope through the
        existing read-only APIs.  It never submits an order and does not
        accept caller supplied account/day identity, so an empty result can be
        promoted to a flat-account fact only when the terminal QueryResult and
        current session agree.
        """

        self._ensure_connected()
        try:
            if isinstance(ttl_seconds, bool):
                raise ValueError
            ttl = float(ttl_seconds)
        except (TypeError, ValueError):
            ttl = float("nan")
        if not isfinite(ttl) or ttl <= 0:
            raise CtpPositionEvidenceError("position_query_expiry_invalid")
        result = self.query_positions_result(timeout=timeout)
        session_scope = self.get_query_session_scope()
        now = datetime.now(timezone.utc)
        monotonic_now = time.monotonic()
        source = result.query_source
        try:
            expires = source.completed_at_utc + timedelta(seconds=ttl)
            monotonic_expires = source.completed_monotonic + ttl
        except (AttributeError, TypeError):
            expires = now + timedelta(seconds=ttl)
            monotonic_expires = monotonic_now + ttl
        return build_ctp_position_evidence(
            result,
            session_state=session_scope,
            now_utc=now,
            expires_at_utc=expires,
            monotonic_now=monotonic_now,
            monotonic_expires_at=monotonic_expires,
        )

    def query_orders_result(self, **kwargs: Any) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_orders_result(**kwargs)

    query_order_result = query_orders_result

    def query_trades_result(self, **kwargs: Any) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_trades_result(**kwargs)

    def query_instruments_result(
        self,
        instrument_id: str = "",
        exchange_id: str = "",
        product_id: str = "",
        timeout: float = 5,
        **kwargs: Any,
    ) -> QueryResult[Any]:
        self._ensure_connected()
        query_kwargs = {
            "instrument_id": instrument_id,
            "exchange_id": exchange_id,
            "timeout": timeout,
            **kwargs,
        }
        if product_id:
            query_kwargs["product_id"] = product_id
        return self._trader.query_instruments_result(**query_kwargs)

    def query_instrument_margin_rate_result(self, *args: Any, **kwargs: Any) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_instrument_margin_rate_result(*args, **kwargs)

    def query_instrument_commission_rate_result(
        self, *args: Any, **kwargs: Any
    ) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_instrument_commission_rate_result(*args, **kwargs)

    def query_settlement_confirmation_result(self, **kwargs: Any) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_settlement_confirmation_result(**kwargs)

    def query_depth_market_data_result(self, **kwargs: Any) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_depth_market_data_result(**kwargs)

    def query_option_instrument_trade_cost_result(
        self, *args: Any, **kwargs: Any
    ) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_option_instrument_trade_cost_result(*args, **kwargs)

    def query_option_instrument_commission_rate_result(
        self, *args: Any, **kwargs: Any
    ) -> QueryResult[Any]:
        self._ensure_connected()
        return self._trader.query_option_instrument_commission_rate_result(*args, **kwargs)


class CtpMarketStream(BaseDataStream):
    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        super().__init__(data_queue, **kwargs)
        resolved_kwargs, self.ctp_env_name = _resolve_ctp_runtime_kwargs(kwargs)
        self.ctp_env_profile = resolved_kwargs.get("ctp_env_profile", self.ctp_env_name)
        self.ctp_env_readiness = resolved_kwargs.get("ctp_env_readiness", "unknown")
        self.md_front = resolved_kwargs.get("md_front", "")
        self.broker_id = resolved_kwargs.get("broker_id", "")
        self.user_id = resolved_kwargs.get("user_id", "")
        self.password = resolved_kwargs.get("password", "")
        self.topics = resolved_kwargs.get("topics", [])
        # A CTP MD feed can carry options and futures in one subscription.  A
        # default of FUTURE would silently mislabel the option legs, so an
        # omitted identity stays explicit and conservative instead.
        self.asset_type = str(resolved_kwargs.get("asset_type") or "UNKNOWN")
        self._md_client = None
        self._ingest_seq = 0
        # The native client generation resets when a new ``MdClient`` object
        # is constructed.  Keep a stream-local, monotonically increasing
        # generation as the externally visible boundary instead.
        self._observed_client_generation: int | None = None
        self._connection_generation = 0
        self._md_callback_lock = threading.RLock()
        self._md_client_token = 0
        # A callback closure receives this opaque capability only from
        # ``connect``.  Direct test seams and caller-invoked private methods
        # may still emit diagnostic rows, but cannot issue a managed receipt.
        self._managed_quote_v2_callback_capability: object | None = None
        self._managed_quote_v2_stream_token = object()
        self._volume_tracker = CtpVolumeDeltaTracker()
        self._subscription_epoch = 0
        self._quote_v2_default_metadata = self._quote_v2_metadata(
            resolved_kwargs.get("quote_v2_metadata")
        )
        raw_metadata_by_instrument = resolved_kwargs.get("quote_v2_metadata_by_instrument")
        self._quote_v2_metadata_by_instrument = {
            str(instrument): self._quote_v2_metadata(metadata)
            for instrument, metadata in (
                raw_metadata_by_instrument.items()
                if isinstance(raw_metadata_by_instrument, dict)
                else ()
            )
            if str(instrument)
        }
        self._quote_v2_subscription_metadata: dict[str, dict[str, Any]] = {}
        self._has_connected_once = False
        self._register_quote_v2_topics(self.topics)

    @staticmethod
    def _quote_v2_metadata(value: Any) -> dict[str, Any]:
        """Copy explicit externally supplied V2 diagnostic fields.

        The CTP MD API does not prove clock calibration, rules identity or an
        execution-ready subscription.  These values stay observable on the
        native row for diagnostics, but cannot qualify the managed receipt
        used by the parent SDK.  Missing fields therefore remain empty,
        ``unknown`` or false instead of being inferred from local process time.
        """

        if not isinstance(value, dict):
            return {}
        names = (
            "asset_type",
            "product_class",
            "contract_type",
            "option_type",
            "underlying_instrument",
            "strike_price",
            "rules_hash",
            "clock_domain_id",
            "source",
            "source_clock_quality",
            "receive_clock_quality",
            "source_clock_error_ms",
            "receive_clock_error_ms",
            "freshness_verified",
        )
        return {name: value[name] for name in names if name in value}

    @staticmethod
    def _topic_symbols(topic: Any) -> list[str]:
        if not isinstance(topic, dict) or topic.get("topic") not in {
            "tick",
            "ticker",
            "depth",
        }:
            return []
        values = [topic.get("symbol", "")]
        listed = topic.get("symbol_list", [])
        if isinstance(listed, (list, tuple, set, frozenset)):
            values.extend(listed)
        return [str(value).strip() for value in values if str(value).strip()]

    def _register_quote_v2_topics(self, topics: Any) -> list[str]:
        records = [
            (instrument, topic)
            for topic in (topics or [])
            for instrument in self._topic_symbols(topic)
        ]
        if not records:
            return []

        # One subscribe request receives one epoch shared by every requested
        # leg.  A subsequent (including reconnect) request advances it.
        self._subscription_epoch += 1
        epoch = self._subscription_epoch
        instruments: list[str] = []
        for instrument, topic in records:
            metadata = dict(self._quote_v2_default_metadata)
            metadata.update(self._quote_v2_metadata_by_instrument.get(instrument, {}))
            metadata.update(self._quote_v2_metadata(topic.get("quote_v2")))
            metadata.update(self._quote_v2_metadata(topic))
            metadata["subscription_epoch"] = epoch
            self._quote_v2_subscription_metadata[instrument] = metadata
            if instrument not in instruments:
                instruments.append(instrument)
        return instruments

    def _advance_quote_v2_subscription_epoch(self) -> None:
        """Fence all active instruments when a client reconnects.

        The CTP callback does not carry a subscription identifier.  Retagging
        every active instrument before its reconnect subscription makes a
        delayed quote from the previous client distinguishable to downstream
        consumers without pretending that the source itself supplied that
        proof.
        """

        if not self._quote_v2_subscription_metadata:
            return
        self._subscription_epoch += 1
        for metadata in self._quote_v2_subscription_metadata.values():
            metadata["subscription_epoch"] = self._subscription_epoch

    def _advance_quote_v2_connection_generation(self, *, advance_subscription_epoch: bool) -> None:
        """Start a new stream-local quote generation.

        CTP's native generation belongs to one ``MdClient`` instance, whereas
        the public quote stream can outlive several client instances.  This
        helper makes both an explicit reconnect and an in-place native
        reconnect a hard volume/cohort boundary.
        """

        self._connection_generation += 1
        self._ingest_seq = 0
        if advance_subscription_epoch:
            self._advance_quote_v2_subscription_epoch()

    def _is_current_md_callback(self, client: Any, client_token: int | None) -> bool:
        """Return whether a callback still belongs to the active MD client."""

        return client is self._md_client and client_token == self._md_client_token

    def _attach_managed_quote_v2_receipt(self, row: CtpTickerData) -> None:
        """Bind one native callback row to this stream without self-qualifying it.

        The raw CTP callback itself does not establish the calibration and
        rules evidence needed for execution.  The receipt therefore carries
        a managed producer identity and lifecycle fence while explicitly
        withholding every qualification fact.  Public metadata can be useful
        for diagnostics, but it cannot alter this receipt.
        """

        row._managed_quote_v2_receipt = _CtpManagedQuoteV2Receipt(
            _CTP_MANAGED_QUOTE_V2_RECEIPT_SEAL,
            self,
            self._managed_quote_v2_stream_token,
            row,
            str(row.get_symbol_name() or "").strip(),
            int(self._connection_generation or 0),
            int(row.subscription_epoch or 0),
            int(row.ingest_seq or 0),
            "ctp.native.md",
            "",
            "",
            "unknown",
            "unknown",
            None,
            None,
            False,
            False,
        )

    def connect(self):
        with self._md_callback_lock:
            self.state = ConnectionState.CONNECTING
            self._md_client_token += 1
            client_token = self._md_client_token
            callback_capability = object()
            self._managed_quote_v2_callback_capability = callback_capability
            self._advance_quote_v2_connection_generation(
                advance_subscription_epoch=self._has_connected_once
            )
            self._observed_client_generation = None
            client = ctp_client.MdClient(self.md_front, self.broker_id, self.user_id, self.password)
            self._md_client = client
            # Bind the callback to this concrete client and its lifecycle
            # token.  A late callback from a stopped/replaced client cannot be
            # relabelled with the current client's generation or epoch.
            client.on_tick = (
                lambda tick_field, _client=client, _token=client_token, _capability=callback_capability: (
                    self._on_tick(
                        tick_field,
                        client=_client,
                        client_token=_token,
                        _managed_callback_capability=_capability,
                    )
                )
            )
            client.on_login = lambda login_field, _client=client, _token=client_token: (
                self._on_login(login_field, client=_client, client_token=_token)
            )
            client.on_error = lambda rsp_info, _client=client, _token=client_token: self._on_error(
                rsp_info, client=_client, client_token=_token
            )
            instruments = list(self._quote_v2_subscription_metadata)
            if instruments:
                client.subscribe(instruments)
            client.start(block=False)
            self._has_connected_once = True

    def _on_login(self, login_field, *, client: Any = None, client_token: int | None = None):
        with self._md_callback_lock:
            if client is not None and not self._is_current_md_callback(client, client_token):
                return
            self.state = ConnectionState.AUTHENTICATED

    def _on_tick(
        self,
        tick_field,
        *,
        client: Any = None,
        client_token: int | None = None,
        _managed_callback_capability: object | None = None,
    ):
        with self._md_callback_lock:
            # Direct calls are retained for the existing offline unit-test
            # seam.  Native callbacks always carry a client/token pair and
            # must match both identities before touching state.
            native_managed_callback = (
                client is not None
                and self._managed_quote_v2_callback_capability is not None
                and _managed_callback_capability is self._managed_quote_v2_callback_capability
                and self._is_current_md_callback(client, client_token)
            )
            if client is None:
                client = self._md_client
            elif not self._is_current_md_callback(client, client_token):
                return
            if client is None:
                return

            received_at = datetime.now(timezone.utc)
            received_monotonic_ns = time.monotonic_ns()
            tick_dict = _ctp_field_to_dict(tick_field)
            symbol = str(tick_dict.get("InstrumentID", "") or "")
            try:
                client_generation = int(getattr(client, "connection_generation", 0) or 0)
            except (TypeError, ValueError):
                client_generation = 0
            if self._observed_client_generation is None:
                self._observed_client_generation = client_generation
                if self._connection_generation <= 0:
                    self._advance_quote_v2_connection_generation(advance_subscription_epoch=False)
            elif client_generation != self._observed_client_generation:
                self._observed_client_generation = client_generation
                self._advance_quote_v2_connection_generation(advance_subscription_epoch=True)
            self._ingest_seq += 1
            metadata = dict(self._quote_v2_default_metadata)
            metadata.update(self._quote_v2_metadata_by_instrument.get(symbol, {}))
            metadata.update(self._quote_v2_subscription_metadata.get(symbol, {}))
            row = CtpTickerData(
                tick_dict,
                symbol,
                metadata.get("asset_type", self.asset_type),
                True,
                connection_generation=self._connection_generation,
                ingest_seq=self._ingest_seq,
                recv_time_utc=received_at,
                recv_monotonic_ns=received_monotonic_ns,
                subscription_epoch=metadata.get("subscription_epoch", 0),
                rules_hash=metadata.get("rules_hash", ""),
                clock_domain_id=metadata.get("clock_domain_id", ""),
                source=metadata.get("source", "ctp.native.md"),
                source_clock_quality=metadata.get("source_clock_quality", "unknown"),
                receive_clock_quality=metadata.get("receive_clock_quality", "unknown"),
                source_clock_error_ms=metadata.get("source_clock_error_ms"),
                receive_clock_error_ms=metadata.get("receive_clock_error_ms"),
                freshness_verified=metadata.get("freshness_verified", False),
                product_class=metadata.get("product_class"),
                contract_type=metadata.get("contract_type"),
                option_type=metadata.get("option_type"),
                underlying_instrument=metadata.get("underlying_instrument"),
                strike_price=metadata.get("strike_price"),
            )
            row.init_data()
            row.resolve_event_time()
            if _validate_ctp_quote(row):
                self._volume_tracker.apply(row)
            else:
                row.apply_volume_delta(0, complete=False, quality="INVALID_QUOTE")
            if native_managed_callback:
                self._attach_managed_quote_v2_receipt(row)
            self.push_data(row)

    def _on_error(self, rsp_info, *, client: Any = None, client_token: int | None = None):
        with self._md_callback_lock:
            if client is not None and not self._is_current_md_callback(client, client_token):
                return
            self.state = ConnectionState.ERROR

    def disconnect(self):
        with self._md_callback_lock:
            client = self._md_client
            # Invalidate before stopping so a callback already queued by the
            # old native client cannot enter after this lifecycle boundary.
            self._md_client_token += 1
            self._managed_quote_v2_callback_capability = None
            self._md_client = None
            self._observed_client_generation = None
            self.state = ConnectionState.DISCONNECTED
        if client is not None:
            client.stop()

    def subscribe_topics(self, topics):
        with self._md_callback_lock:
            instruments = self._register_quote_v2_topics(topics)
            if instruments and self._md_client is not None:
                self._md_client.subscribe(instruments)

    def _run_loop(self):
        self.connect()
        while self._running:
            time.sleep(1)


class CtpTradeStream(BaseDataStream):
    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        self._request_feed = kwargs.pop("request_feed", None)
        super().__init__(data_queue, **kwargs)
        resolved_kwargs, self.ctp_env_name = _resolve_ctp_runtime_kwargs(kwargs)
        self.ctp_env_profile = resolved_kwargs.get("ctp_env_profile", self.ctp_env_name)
        self.ctp_env_readiness = resolved_kwargs.get("ctp_env_readiness", "unknown")
        self.td_front = resolved_kwargs.get("td_front", "")
        self.broker_id = resolved_kwargs.get("broker_id", "")
        self.user_id = resolved_kwargs.get("user_id", "")
        self.password = resolved_kwargs.get("password", "")
        self.auth_code = resolved_kwargs.get("auth_code", "0000000000000000")
        self.app_id = resolved_kwargs.get("app_id", "simnow_client_test")
        self.auto_settlement_confirm = _as_bool(
            resolved_kwargs.get("auto_settlement_confirm"), default=False
        )
        self.asset_type = resolved_kwargs.get("asset_type", "FUTURE")
        self._trader = None
        self._owns_trader = False

    def connect(self):
        self.state = ConnectionState.CONNECTING
        if self.auto_settlement_confirm is not False:
            raise ctp_client.CtpExecutionGateError(
                "ctp_execution_gate_auto_settlement_confirm_enabled"
            )
        if self._request_feed is not None:
            self._request_feed.connect()
            self._trader = self._request_feed.trader_client
            self._owns_trader = False
            if self._trader is None:
                self.state = ConnectionState.ERROR
                raise BtConnectionError("CTP", "shared request feed has no TraderClient")
            if getattr(self._trader, "auto_settlement_confirm", None) is not False:
                raise ctp_client.CtpExecutionGateError(
                    "ctp_execution_gate_auto_settlement_confirm_enabled"
                )
        else:
            self._trader = ctp_client.TraderClient(
                self.td_front,
                self.broker_id,
                self.user_id,
                self.password,
                app_id=self.app_id,
                auth_code=self.auth_code,
                auto_settlement_confirm=self.auto_settlement_confirm,
            )
            self._owns_trader = True
        self._trader.on_order = self._on_order
        self._trader.on_trade = self._on_trade
        self._trader.on_login = self._on_login
        self._trader.on_error = self._on_error
        if self._owns_trader:
            self._trader.start(block=False)
        elif getattr(self._trader, "is_read_only_ready", False):
            self.state = ConnectionState.AUTHENTICATED

    def _on_login(self, login_field):
        self.state = ConnectionState.AUTHENTICATED

    def _on_order(self, order_field):
        order_dict = _ctp_field_to_dict(order_field)
        session = self._trader.get_session_state() if self._trader is not None else {}
        order_dict.setdefault("TradingDay", session.get("trading_day", ""))
        order_dict.setdefault("InvestorID", self.user_id)
        symbol = order_dict.get("InstrumentID", "")
        self.push_data(CtpOrderData(order_dict, symbol, self.asset_type, True))

    def _on_trade(self, trade_field):
        trade_dict = _ctp_field_to_dict(trade_field)
        session = self._trader.get_session_state() if self._trader is not None else {}
        trade_dict.setdefault("TradingDay", session.get("trading_day", ""))
        trade_dict.setdefault("InvestorID", self.user_id)
        symbol = trade_dict.get("InstrumentID", "")
        self.push_data(CtpTradeData(trade_dict, symbol, self.asset_type, True))

    def _on_error(self, rsp_info):
        self.state = ConnectionState.ERROR

    def disconnect(self):
        if self._trader is not None:
            if self._owns_trader:
                self._trader.stop()
            else:
                for callback_name, callback in (
                    ("on_order", self._on_order),
                    ("on_trade", self._on_trade),
                    ("on_login", self._on_login),
                    ("on_error", self._on_error),
                ):
                    if getattr(self._trader, callback_name, None) == callback:
                        setattr(self._trader, callback_name, None)
            self._trader = None
        self._owns_trader = False
        self.state = ConnectionState.DISCONNECTED

    def subscribe_topics(self, topics):
        return None

    def _run_loop(self):
        self.connect()
        while self._running:
            time.sleep(1)

    @property
    def trader_client(self):
        return self._trader


class CtpRequestDataFuture(CtpRequestData):
    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        super().__init__(data_queue, **kwargs)
        self.asset_type = kwargs.get("asset_type", "FUTURE")
        self._params = CtpExchangeDataFuture()


__all__ = [
    "CTP_DIRECTION_FLAG",
    "CTP_OFFSET_FLAG",
    "CtpMarketStream",
    "CtpRequestData",
    "CtpRequestDataFuture",
    "CtpTradeStream",
    "CtpVolumeDeltaTracker",
    "_ctp_field_to_dict",
]
