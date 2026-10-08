"""Fixed, local worker protocol for the unregistered SimNow C01 candidate.

This module is deliberately standard-library-only.  It defines the wire shape
between a supervising parent and one fixed C01 TD worker; it does not load an
SDK, read configuration, access a provider, or decide certification PASS.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import ntpath
import ipaddress
import math
import re
import unicodedata
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation, localcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


PROTOCOL_NAME = "backtrader.simnow.c01.v2"
PROTOCOL_VERSION = 2
ACCOUNT_SCOPE_SCHEME = "simnow.c01.account.v1"
CREDENTIAL_BINDING_SCHEME = "simnow.c01.credentials.v1"
PRIVATE_INPUT_PROTOCOL = "iteration41.simnow-c01-private-input.v2"
LAUNCH_MESSAGE = "launch"
WORKER_MESSAGE = "worker_receipt"
MAX_CREDENTIAL_PACKET_BYTES = 128 * 1024
MAX_LAUNCH_FRAME_BYTES = 256 * 1024
MAX_WORKER_FRAME_BYTES = 1024 * 1024
MAX_PRIVATE_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_CALLBACKS = 10000
PRIVATE_SNAPSHOT_MESSAGE = "private_snapshot_v2"
SDK_QUERY_RESULT_TYPE = "bt_api_ctp.query.QueryResult"
SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE = "SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE"
SDK_QUERY_EVIDENCE_MAX_TTL_SECONDS = 35.0
RSP_INFO_ABSENT = "RSP_INFO_ABSENT"
RSP_INFO_ERROR_ID_PRESENT = "RSP_INFO_ERROR_ID_PRESENT"
POSITION_BUCKET_SCHEMA = "simnow.c01.ctp-gross-position-buckets.v2"
ACCOUNT_ECONOMICS_SCHEMA = "simnow.c01.ctp-trading-account-economics.v3"
ORDER_ECONOMICS_SCHEMA = "simnow.c01.ctp-active-order-economics.v2"
POSITION_BUCKET_DIMENSIONS = (
    "ExchangeID",
    "InstrumentID",
    "PosiDirection",
    "HedgeFlag",
    "PositionDate",
)
ACCOUNT_DIMENSION_FIELDS = ("BrokerID", "AccountID", "CurrencyID", "BizType", "TradingDay")
ACCOUNT_NUMERIC_MEASURES = (
    "PreMortgage",
    "PreCredit",
    "PreDeposit",
    "PreBalance",
    "PreMargin",
    "InterestBase",
    "Interest",
    "Deposit",
    "Withdraw",
    "FrozenMargin",
    "FrozenCash",
    "FrozenCommission",
    "CurrMargin",
    "CashIn",
    "Commission",
    "CloseProfit",
    "PositionProfit",
    "Balance",
    "Available",
    "WithdrawQuota",
    "Reserve",
    "SettlementID",
    "Credit",
    "Mortgage",
    "ExchangeMargin",
    "DeliveryMargin",
    "ExchangeDeliveryMargin",
    "ReserveBalance",
    "PreFundMortgageIn",
    "PreFundMortgageOut",
    "FundMortgageIn",
    "FundMortgageOut",
    "FundMortgageAvailable",
    "MortgageableFund",
    "SpecProductMargin",
    "SpecProductFrozenMargin",
    "SpecProductCommission",
    "SpecProductFrozenCommission",
    "SpecProductPositionProfit",
    "SpecProductCloseProfit",
    "SpecProductPositionProfitByAlg",
    "SpecProductExchangeMargin",
    "FrozenSwap",
    "RemainSwap",
)
ACCOUNT_INTEGER_MEASURES = frozenset({"SettlementID"})
ACCOUNT_DIAGNOSTIC_FIELD_SOURCES = MappingProxyType(
    {
        "cash": "Available",
        "available_funds": "Available",
        "equity": "Balance",
    }
)
ACCOUNT_NONNEGATIVE_MEASURES = frozenset(
    {
        "FrozenMargin",
        "FrozenCash",
        "FrozenCommission",
        "SpecProductFrozenMargin",
        "SpecProductFrozenCommission",
        "FrozenSwap",
        "SettlementID",
    }
)
ORDER_IDENTITY_TEXT_FIELDS = (
    "BrokerID",
    "InvestorID",
    "ExchangeID",
    "InstrumentID",
    "OrderSysID",
    "OrderRef",
    "TradingDay",
)
ORDER_IDENTITY_INTEGER_FIELDS = ("FrontID", "SessionID")
ORDER_DECIMAL_MEASURES = ("LimitPrice", "StopPrice")
ORDER_INTEGER_MEASURES = (
    "VolumeTotalOriginal",
    "VolumeTraded",
    "VolumeTotal",
    "MinVolume",
    "IsAutoSuspend",
    "UserForceClose",
)
ORDER_TEXT_MEASURES = (
    "Direction",
    "CombOffsetFlag",
    "CombHedgeFlag",
    "OrderPriceType",
    "TimeCondition",
    "VolumeCondition",
    "ContingentCondition",
    "ForceCloseReason",
    "OrderStatus",
    "OrderSubmitStatus",
)
POSITION_NUMERIC_MEASURES = (
    "YdPosition",
    "Position",
    "LongFrozen",
    "ShortFrozen",
    "LongFrozenAmount",
    "ShortFrozenAmount",
    "OpenVolume",
    "CloseVolume",
    "OpenAmount",
    "CloseAmount",
    "PositionCost",
    "PreMargin",
    "UseMargin",
    "FrozenMargin",
    "FrozenCash",
    "FrozenCommission",
    "CashIn",
    "Commission",
    "CloseProfit",
    "PositionProfit",
    "PreSettlementPrice",
    "SettlementPrice",
    "SettlementID",
    "OpenCost",
    "ExchangeMargin",
    "CombPosition",
    "CombLongFrozen",
    "CombShortFrozen",
    "CloseProfitByDate",
    "CloseProfitByTrade",
    "TodayPosition",
    "MarginRateByMoney",
    "MarginRateByVolume",
    "StrikeFrozen",
    "StrikeFrozenAmount",
    "AbandonFrozen",
    "YdStrikeFrozen",
    "PositionCostOffset",
    "TasPosition",
    "TasPositionCost",
)
POSITION_TEXT_MEASURES = ("TradingDay", "InvestUnitID", "reserve1")
POSITION_INTEGER_MEASURES = frozenset(
    {
        "Position",
        "TodayPosition",
        "YdPosition",
        "LongFrozen",
        "ShortFrozen",
        "CombLongFrozen",
        "CombShortFrozen",
        "StrikeFrozen",
        "AbandonFrozen",
        "YdStrikeFrozen",
        "OpenVolume",
        "CloseVolume",
        "CombPosition",
        "TasPosition",
        "SettlementID",
    }
)
POSITION_NONNEGATIVE_MEASURES = frozenset(
    {
        *POSITION_INTEGER_MEASURES,
        "LongFrozenAmount",
        "ShortFrozenAmount",
        "FrozenMargin",
        "FrozenCash",
        "FrozenCommission",
        "StrikeFrozenAmount",
        "SettlementID",
    }
)
KNOWN_CTP_EXCHANGES = frozenset({"CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"})

_HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}" r"(?:\.\d{1,9})?Z$")
_REQUEST_KINDS = frozenset({"authenticate", "login", "query"})
_PHASES = frozenset({"baseline", "final"})
_FAMILIES = frozenset({"orders", "positions", "funds"})
_CALLBACK_KINDS = _REQUEST_KINDS | frozenset({"order_activity", "trade_activity"})
_CALLBACK_NAMES = frozenset(
    {
        "OnRspAuthenticate",
        "OnRspUserLogin",
        "OnRspQryOrder",
        "OnRspQryInvestorPosition",
        "OnRspQryTradingAccount",
        "OnRtnOrder",
        "OnRtnTrade",
    }
)
_QUERY_METHODS = {
    "orders": ("ReqQryOrder", "OnRspQryOrder"),
    "positions": ("ReqQryInvestorPosition", "OnRspQryInvestorPosition"),
    "funds": ("ReqQryTradingAccount", "OnRspQryTradingAccount"),
}


class C01ProtocolError(ValueError):
    """Raised when a launch or worker frame is malformed or ambiguous."""


def _strict_json_object(pairs: list) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise C01ProtocolError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise C01ProtocolError("nonstandard_json_constant")


def _parse_frame(frame: bytes, *, limit: int) -> Dict[str, Any]:
    if not isinstance(frame, bytes) or not frame or len(frame) > limit:
        raise C01ProtocolError("frame_size_invalid")
    if not frame.endswith(b"\n") or frame.count(b"\n") != 1:
        raise C01ProtocolError("frame_must_be_one_json_line")
    try:
        value = json.loads(
            frame[:-1].decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except C01ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise C01ProtocolError("frame_json_invalid") from None
    if not isinstance(value, dict):
        raise C01ProtocolError("frame_root_must_be_object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: Tuple[str, ...], where: str) -> None:
    if set(value) != set(expected):
        raise C01ProtocolError(where + "_keys_invalid")


def _string(value: Any, where: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise C01ProtocolError(where + "_invalid")
    return value


def _int(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise C01ProtocolError(where + "_invalid")
    return value


def _nullable_int(value: Any, where: str, *, minimum: int = 0) -> Optional[int]:
    if value is None:
        return None
    return _int(value, where, minimum=minimum)


def _bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise C01ProtocolError(where + "_invalid")
    return value


def _nullable_bool(value: Any, where: str) -> Optional[bool]:
    if value is None:
        return None
    return _bool(value, where)


def _validate_sdk_query_result(
    value: Any, request: Mapping[str, Any], client: Mapping[str, Any]
) -> None:
    if not isinstance(value, dict):
        raise C01ProtocolError("sdk_query_result_invalid")
    _exact_keys(
        value,
        (
            "result_type",
            "request_type",
            "request_id",
            "connection_generation",
            "complete",
            "evidence_complete",
            "is_last_seen",
            "timed_out",
            "unsupported",
            "error_code",
            "account_fingerprint",
            "started_at_utc",
            "completed_at_utc",
            "error_message",
            "submit_code",
            "record_count",
            "late_callback_count",
            "error_semantics",
            "account_fingerprint",
            "started_at_utc",
            "completed_at_utc",
            "error_message",
            "evidence_complete",
            "records_sha256",
            "callback_records_sha256",
            "query_source",
        ),
        "sdk_query_result",
    )
    if value["result_type"] != SDK_QUERY_RESULT_TYPE:
        raise C01ProtocolError("sdk_query_result_type_invalid")
    expected_request_type = {
        "orders": "orders",
        "positions": "positions",
        "funds": "account",
    }[request["family"]]
    if value["request_type"] != expected_request_type:
        raise C01ProtocolError("sdk_query_result_request_type_invalid")
    if value["request_id"] != request["request_id"]:
        raise C01ProtocolError("sdk_query_result_request_id_mismatch")
    _int(value["connection_generation"], "sdk_query_result_generation", minimum=1)
    if value["connection_generation"] != client["arrival_generation"]:
        raise C01ProtocolError("sdk_query_result_generation_mismatch")
    _bool(value["complete"], "sdk_query_result_complete")
    _bool(value["is_last_seen"], "sdk_query_result_is_last_seen")
    _bool(value["timed_out"], "sdk_query_result_timed_out")
    _bool(value["unsupported"], "sdk_query_result_unsupported")
    _bool(value["evidence_complete"], "sdk_query_result_evidence_complete")
    error_code = _nullable_int(value["error_code"], "sdk_query_result_error_code", minimum=0)
    _nullable_int(value["submit_code"], "sdk_query_result_submit_code", minimum=0)
    _int(value["record_count"], "sdk_query_result_record_count", minimum=0)
    _int(value["late_callback_count"], "sdk_query_result_late_callback_count", minimum=0)
    account_fingerprint = _bounded_string(
        value["account_fingerprint"], "sdk_query_result_account_fingerprint", maximum=256
    )
    if value["evidence_complete"] is not value["complete"]:
        raise C01ProtocolError("sdk_query_result_evidence_complete_mismatch")
    if type(value["error_message"]) is not str or value["error_message"] != "":
        raise C01ProtocolError("sdk_query_result_error_message_invalid")
    started_at = _sdk_utc_datetime(value["started_at_utc"], "sdk_query_result_started_at_utc")
    completed_at = _sdk_utc_datetime(value["completed_at_utc"], "sdk_query_result_completed_at_utc")
    if completed_at < started_at:
        raise C01ProtocolError("sdk_query_result_time_order_invalid")
    semantic = _string(value["error_semantics"], "sdk_query_result_error_semantics")
    if error_code is not None:
        raise C01ProtocolError("sdk_query_result_success_error_code_not_null")
    if semantic != SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE:
        raise C01ProtocolError("sdk_query_result_error_semantics_mismatch")
    result_records_sha256 = _digest(value["records_sha256"], "sdk_query_result_records_sha256")
    callback_records_sha256 = _digest(
        value["callback_records_sha256"], "sdk_callback_records_sha256"
    )
    source = value["query_source"]
    if not isinstance(source, dict):
        raise C01ProtocolError("sdk_query_source_invalid")
    _exact_keys(
        source,
        (
            "source_type",
            "seal_valid",
            "issuer_is_client_query_lane",
            "request_type",
            "request_id",
            "account_fingerprint",
            "connection_generation",
            "trading_day",
            "broker_id",
            "investor_id",
            "request_filters",
            "explicit_request_filters",
            "started_at_utc",
            "completed_at_utc",
            "started_monotonic_hex",
            "completed_monotonic_hex",
            "clock_domain_id",
            "records_sha256",
            "trusted_expires_at_utc",
            "trusted_expires_monotonic_hex",
        ),
        "sdk_query_source",
    )
    if (
        source["source_type"] != "bt_api_ctp.query._QuerySource"
        or source["seal_valid"] is not True
        or source["issuer_is_client_query_lane"] is not True
        or source["request_type"] != value["request_type"]
        or source["request_id"] != value["request_id"]
        or source["connection_generation"] != value["connection_generation"]
        or source["account_fingerprint"] != account_fingerprint
        or source["started_at_utc"] != value["started_at_utc"]
        or source["completed_at_utc"] != value["completed_at_utc"]
        or source["clock_domain_id"] != "python.time.monotonic"
    ):
        raise C01ProtocolError("sdk_query_source_binding_invalid")
    _int(source["request_id"], "sdk_query_source_request_id", minimum=1)
    _int(source["connection_generation"], "sdk_query_source_generation", minimum=1)
    trading_day = _string(source["trading_day"], "sdk_query_source_trading_day")
    if not re.fullmatch(r"\d{8}", trading_day):
        raise C01ProtocolError("sdk_query_source_trading_day_invalid")
    broker_id = _bounded_string(source["broker_id"], "sdk_query_source_broker_id", maximum=10)
    investor_id = _bounded_string(source["investor_id"], "sdk_query_source_investor_id", maximum=32)
    request_filters = source["request_filters"]
    if not isinstance(request_filters, list):
        raise C01ProtocolError("sdk_query_source_filters_invalid")
    expected_filter_names = (
        ("BrokerID", "ExchangeID", "InstrumentID", "InvestorID", "OrderSysID")
        if request["family"] == "orders"
        else ("BrokerID", "InvestorID")
    )
    filters = []
    for item in request_filters:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
        ):
            raise C01ProtocolError("sdk_query_source_filter_invalid")
        filters.append((item[0], item[1]))
    if tuple(name for name, _item in filters) != expected_filter_names:
        raise C01ProtocolError("sdk_query_source_filter_names_invalid")
    filter_values = dict(filters)
    if (
        filter_values.get("BrokerID") != broker_id
        or filter_values.get("InvestorID") != investor_id
        or any(
            filter_values.get(name) != ""
            for name in ("ExchangeID", "InstrumentID", "OrderSysID")
            if name in filter_values
        )
    ):
        raise C01ProtocolError("sdk_query_source_filter_binding_invalid")
    explicit_filters = source["explicit_request_filters"]
    if type(explicit_filters) is not list or explicit_filters != []:
        raise C01ProtocolError("sdk_query_source_explicit_filters_invalid")
    source_started_at = _sdk_utc_datetime(
        source["started_at_utc"], "sdk_query_source_started_at_utc"
    )
    source_completed_at = _sdk_utc_datetime(
        source["completed_at_utc"], "sdk_query_source_completed_at_utc"
    )
    trusted_expires_at = _sdk_utc_datetime(
        source["trusted_expires_at_utc"], "sdk_query_source_trusted_expiry_utc"
    )
    if (
        source_started_at != started_at
        or source_completed_at != completed_at
        or trusted_expires_at
        != completed_at + timedelta(seconds=SDK_QUERY_EVIDENCE_MAX_TTL_SECONDS)
    ):
        raise C01ProtocolError("sdk_query_source_time_binding_invalid")
    started_monotonic = _sdk_float_hex(
        source["started_monotonic_hex"], "sdk_query_source_started_monotonic"
    )
    completed_monotonic = _sdk_float_hex(
        source["completed_monotonic_hex"], "sdk_query_source_completed_monotonic"
    )
    trusted_expires_monotonic = _sdk_float_hex(
        source["trusted_expires_monotonic_hex"], "sdk_query_source_trusted_expiry_monotonic"
    )
    if (
        started_monotonic >= completed_monotonic
        or trusted_expires_monotonic != completed_monotonic + SDK_QUERY_EVIDENCE_MAX_TTL_SECONDS
    ):
        raise C01ProtocolError("sdk_query_source_monotonic_binding_invalid")
    source_records_sha256 = _digest(source["records_sha256"], "sdk_query_source_records_sha256")
    if result_records_sha256 != source_records_sha256:
        raise C01ProtocolError("sdk_query_source_records_digest_mismatch")
    if callback_records_sha256 != result_records_sha256:
        raise C01ProtocolError("sdk_query_callback_records_digest_mismatch")


def canonical_sdk_query_records_sha256(records: Any) -> str:
    """Recompute the pinned SDK's digest over detached JSON-safe query rows.

    This mirrors ``bt_api_ctp.query._query_records_digest`` for the strict C01
    subset (string-keyed mappings, lists/tuples, finite floats and JSON scalar
    values). Unsupported native values fail closed rather than being stringified.
    """

    def canonical(value: Any) -> Any:
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise C01ProtocolError("sdk_query_record_key_invalid")
            return {key: canonical(value[key]) for key in sorted(value)}
        if type(value) in (list, tuple):
            return [canonical(item) for item in value]
        if value is None or type(value) in (str, int, bool):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise C01ProtocolError("sdk_query_record_value_unsupported")

    if type(records) not in (list, tuple):
        raise C01ProtocolError("sdk_query_records_invalid")
    try:
        encoded = json.dumps(
            canonical(tuple(records)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise C01ProtocolError("sdk_query_records_invalid") from None
    return hashlib.sha256(encoded).hexdigest()


def _bounded_string(value: Any, where: str, *, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise C01ProtocolError(where + "_invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise C01ProtocolError(where + "_invalid")
    return value


def _sdk_utc_datetime(value: Any, where: str) -> datetime:
    if type(value) is not str or len(value) > 64 or not value.endswith("+00:00"):
        raise C01ProtocolError(where + "_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise C01ProtocolError(where + "_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or parsed.isoformat() != value:
        raise C01ProtocolError(where + "_invalid")
    return parsed


_SDK_FLOAT_HEX_RE = re.compile(r"0x[0-9a-f]+(?:\.[0-9a-f]*)?p[+-][0-9]+\Z")


def _sdk_float_hex(value: Any, where: str) -> float:
    if type(value) is not str or len(value) > 64 or not _SDK_FLOAT_HEX_RE.fullmatch(value):
        raise C01ProtocolError(where + "_invalid")
    try:
        parsed = float.fromhex(value)
    except ValueError:
        raise C01ProtocolError(where + "_invalid") from None
    if not math.isfinite(parsed) or parsed <= 0 or parsed.hex() != value:
        raise C01ProtocolError(where + "_invalid")
    return parsed


def _validate_callback_error_facts(callback: Mapping[str, Any], *, required: bool) -> None:
    present = callback["rsp_info_present"]
    semantic = callback["error_semantics"]
    if required:
        _bool(present, "callback_rsp_info_present")
        if present is True:
            _int(callback["error_id"], "callback_error_id", minimum=0)
            if semantic != RSP_INFO_ERROR_ID_PRESENT:
                raise C01ProtocolError("callback_error_semantics_mismatch")
        else:
            if callback["error_id"] is not None or semantic != RSP_INFO_ABSENT:
                raise C01ProtocolError("callback_absent_rsp_info_mismatch")
        return
    if present is not None or semantic is not None or callback["error_id"] is not None:
        raise C01ProtocolError("callback_error_facts_unexpected")


def _digest(value: Any, where: str) -> str:
    result = _string(value, where)
    if not _SHA256_RE.fullmatch(result):
        raise C01ProtocolError(where + "_invalid")
    return result


def _utc(value: Any, where: str) -> str:
    result = _string(value, where)
    if not _UTC_RE.fullmatch(result):
        raise C01ProtocolError(where + "_invalid")
    try:
        datetime.strptime(result[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise C01ProtocolError(where + "_invalid") from None
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, repr=False)
class C01PairBindingRef:
    """Hash-only pair identity safe to echo in worker receipts."""

    selected_index: int
    selection_sha256: str
    md_front_sha256: str
    td_front_sha256: str
    selected_at_utc: str

    def __repr__(self) -> str:
        return "C01PairBindingRef(<hash-only binding redacted>)"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_index": self.selected_index,
            "selection_sha256": self.selection_sha256,
            "md_front_sha256": self.md_front_sha256,
            "td_front_sha256": self.td_front_sha256,
            "selected_at_utc": self.selected_at_utc,
        }


@dataclass(frozen=True, repr=False)
class C01PairBinding:
    """Private launch binding for the intact selected MD/TD pair.

    The raw TD endpoint is present only in the parent-to-worker launch frame.
    Its repr is redacted and the worker receipt uses :class:`C01PairBindingRef`.
    """

    selected_index: int
    selection_sha256: str
    md_front_sha256: str
    td_front_sha256: str
    td_front: str
    selected_at_utc: str

    def __repr__(self) -> str:
        return "C01PairBinding(<private td_front redacted>)"

    def to_launch_dict(self) -> Dict[str, Any]:
        return {
            "selected_index": self.selected_index,
            "selection_sha256": self.selection_sha256,
            "md_front_sha256": self.md_front_sha256,
            "td_front_sha256": self.td_front_sha256,
            "td_front": self.td_front,
            "selected_at_utc": self.selected_at_utc,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return only the hash-only identity safe for receipts/diagnostics."""

        return self.to_receipt_ref().to_dict()

    def to_receipt_ref(self) -> C01PairBindingRef:
        return C01PairBindingRef(
            selected_index=self.selected_index,
            selection_sha256=self.selection_sha256,
            md_front_sha256=self.md_front_sha256,
            td_front_sha256=self.td_front_sha256,
            selected_at_utc=self.selected_at_utc,
        )


def _parse_pair_binding(value: Any) -> C01PairBinding:
    if not isinstance(value, dict):
        raise C01ProtocolError("pair_binding_invalid")
    _exact_keys(
        value,
        (
            "selected_index",
            "selection_sha256",
            "md_front_sha256",
            "td_front_sha256",
            "td_front",
            "selected_at_utc",
        ),
        "pair_binding",
    )
    selected_index = _int(value["selected_index"], "selected_index")
    td_front_sha256 = _digest(value["td_front_sha256"], "td_front_sha256")
    td_front = _tcp_ipv4_endpoint(value["td_front"], "td_front")
    if hashlib.sha256(td_front.encode("utf-8")).hexdigest() != td_front_sha256:
        raise C01ProtocolError("td_front_hash_mismatch")
    return C01PairBinding(
        selected_index=selected_index,
        selection_sha256=_digest(value["selection_sha256"], "selection_sha256"),
        md_front_sha256=_digest(value["md_front_sha256"], "md_front_sha256"),
        td_front_sha256=td_front_sha256,
        td_front=td_front,
        selected_at_utc=_utc(value["selected_at_utc"], "selected_at_utc"),
    )


def _parse_pair_ref(value: Any) -> C01PairBindingRef:
    if not isinstance(value, dict):
        raise C01ProtocolError("pair_binding_invalid")
    _exact_keys(
        value,
        (
            "selected_index",
            "selection_sha256",
            "md_front_sha256",
            "td_front_sha256",
            "selected_at_utc",
        ),
        "pair_binding_ref",
    )
    return C01PairBindingRef(
        selected_index=_int(value["selected_index"], "selected_index"),
        selection_sha256=_digest(value["selection_sha256"], "selection_sha256"),
        md_front_sha256=_digest(value["md_front_sha256"], "md_front_sha256"),
        td_front_sha256=_digest(value["td_front_sha256"], "td_front_sha256"),
        selected_at_utc=_utc(value["selected_at_utc"], "selected_at_utc"),
    )


def _tcp_ipv4_endpoint(value: Any, where: str) -> str:
    """Validate the selector's exact canonical ``tcp://IPv4:port`` syntax."""

    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise C01ProtocolError(where + "_invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise C01ProtocolError(where + "_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        address = ipaddress.IPv4Address(host)
    except (ValueError, TypeError):
        raise C01ProtocolError(where + "_invalid") from None
    if (
        type(port) is not int
        or not 1 <= port <= 65535
        or value != "tcp://{}:{}".format(address, port)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise C01ProtocolError(where + "_invalid")
    return value


@dataclass(frozen=True, repr=False)
class C01LaunchRequest:
    """Parent-created, one-run launch packet; credentials remain opaque bytes."""

    run_nonce: str
    parent_pid: int
    expected_worker_source_sha256: str
    pair_binding: C01PairBinding
    account_scope_sha256: str
    credential_binding_sha256: str
    credential_packet: bytes

    def __repr__(self) -> str:
        return "C01LaunchRequest(<private launch fields redacted>)"


@dataclass(frozen=True, repr=False)
class C01PrivateInput:
    """Parsed worker-only credential packet with a deliberately redacted repr."""

    broker_id: str
    user_id: str
    password: str
    app_id: str
    auth_code: str
    product_info: str
    native_flow_directory: str
    evidence_directory: str

    def __repr__(self) -> str:
        return "C01PrivateInput(<redacted>)"


@dataclass(frozen=True, repr=False)
class C01WorkerReceipt:
    """Validated immutable view of the child's single terminal receipt."""

    payload: Mapping[str, Any]

    def __repr__(self) -> str:
        return "C01WorkerReceipt(<private worker evidence redacted>)"

    @property
    def run_nonce(self) -> str:
        return self.payload["run_nonce"]

    @property
    def parent_pid(self) -> int:
        return self.payload["parent_pid"]

    @property
    def worker_pid(self) -> int:
        return self.payload["worker_pid"]

    @property
    def worker_source_sha256(self) -> str:
        return self.payload["worker_source_sha256"]

    @property
    def account_scope_sha256(self) -> str:
        return self.payload["account_scope_sha256"]

    @property
    def credential_binding_sha256(self) -> str:
        return self.payload["credential_binding_sha256"]

    @property
    def pair_binding(self) -> C01PairBindingRef:
        return _parse_pair_ref(dict(self.payload["pair_binding"]))

    def to_dict(self) -> Dict[str, Any]:
        return _thaw(self.payload)


@dataclass(frozen=True, repr=False)
class C01PrivateSnapshot:
    """Parsed, private query artifact; repr never includes account rows."""

    payload: Mapping[str, Any]

    def __repr__(self) -> str:
        return "C01PrivateSnapshot(<private account rows redacted>)"

    @property
    def phase(self) -> str:
        return self.payload["phase"]

    def to_dict(self) -> Dict[str, Any]:
        return _thaw(self.payload)


@dataclass(frozen=True)
class C01ProcessLifecycleReceipt:
    """Parent-observed Windows Job/process facts; never supplied by the child."""

    run_nonce: str
    parent_pid: int
    worker_pid: Optional[int]
    worker_source_sha256: Optional[str]
    assigned_before_resume: bool
    stdin_fully_sent: bool
    stdout_eof: bool
    stderr_eof: bool
    process_exit_observed: bool
    process_exit_code: Optional[int]
    job_active_count: Optional[int]
    handles_closed: bool
    timed_out: bool
    forced_kill: bool
    containment: str
    reason: str
    status: str = "BLOCKED"


@dataclass(frozen=True)
class C01CandidateValidation:
    """Structural eligibility only.  This type has no PASS state."""

    eligible_for_protected_admission: bool
    status: str
    reasons: Tuple[str, ...]
    checked_request_count: int
    checked_query_callback_count: int
    checked_snapshot_count: int


def _encode_json_line(value: Mapping[str, Any], *, limit: int) -> bytes:
    try:
        encoded = (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("ascii")
    except (TypeError, ValueError):
        raise C01ProtocolError("frame_value_not_json_safe") from None
    if len(encoded) > limit:
        raise C01ProtocolError("frame_size_invalid")
    return encoded


def encode_launch_frame(request: C01LaunchRequest) -> bytes:
    """Encode a bounded launch envelope for stdin; never put secrets in argv/env."""

    if not isinstance(request, C01LaunchRequest):
        raise C01ProtocolError("launch_request_type_invalid")
    if not isinstance(request.run_nonce, str) or not _HEX_32_RE.fullmatch(request.run_nonce):
        raise C01ProtocolError("run_nonce_invalid")
    _int(request.parent_pid, "parent_pid", minimum=1)
    _digest(request.expected_worker_source_sha256, "expected_worker_source_sha256")
    _digest(request.account_scope_sha256, "account_scope_sha256")
    _digest(request.credential_binding_sha256, "credential_binding_sha256")
    if not isinstance(request.pair_binding, C01PairBinding):
        raise C01ProtocolError("pair_binding_invalid")
    _parse_pair_binding(request.pair_binding.to_launch_dict())
    if (
        not isinstance(request.credential_packet, bytes)
        or not request.credential_packet
        or len(request.credential_packet) > MAX_CREDENTIAL_PACKET_BYTES
    ):
        raise C01ProtocolError("credential_packet_invalid")
    value = {
        "protocol": PROTOCOL_NAME,
        "message_type": LAUNCH_MESSAGE,
        "version": PROTOCOL_VERSION,
        "case_id": "C01",
        "run_nonce": request.run_nonce,
        "parent_pid": request.parent_pid,
        "expected_worker_source_sha256": request.expected_worker_source_sha256,
        "pair_binding": request.pair_binding.to_launch_dict(),
        "account_scope_sha256": request.account_scope_sha256,
        "credential_binding_sha256": request.credential_binding_sha256,
        "credential_packet_b64": base64.b64encode(request.credential_packet).decode("ascii"),
    }
    return _encode_json_line(value, limit=MAX_LAUNCH_FRAME_BYTES)


def parse_launch_frame(frame: bytes) -> C01LaunchRequest:
    """Parse one supervisor-created stdin packet in the fixed launch schema."""

    value = _parse_frame(frame, limit=MAX_LAUNCH_FRAME_BYTES)
    _exact_keys(
        value,
        (
            "protocol",
            "message_type",
            "version",
            "case_id",
            "run_nonce",
            "parent_pid",
            "expected_worker_source_sha256",
            "pair_binding",
            "account_scope_sha256",
            "credential_binding_sha256",
            "credential_packet_b64",
        ),
        "launch",
    )
    if (
        value["protocol"] != PROTOCOL_NAME
        or value["message_type"] != LAUNCH_MESSAGE
        or type(value["version"]) is not int
        or value["version"] != PROTOCOL_VERSION
        or value["case_id"] != "C01"
    ):
        raise C01ProtocolError("launch_identity_invalid")
    nonce = _string(value["run_nonce"], "run_nonce")
    if not _HEX_32_RE.fullmatch(nonce):
        raise C01ProtocolError("run_nonce_invalid")
    parent_pid = _int(value["parent_pid"], "parent_pid", minimum=1)
    source_sha256 = _digest(value["expected_worker_source_sha256"], "expected_worker_source_sha256")
    account_scope_sha256 = _digest(value["account_scope_sha256"], "account_scope_sha256")
    credential_binding_sha256 = _digest(
        value["credential_binding_sha256"], "credential_binding_sha256"
    )
    packet_b64 = _string(value["credential_packet_b64"], "credential_packet_b64")
    try:
        packet = base64.b64decode(packet_b64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error):
        raise C01ProtocolError("credential_packet_invalid") from None
    if not packet or len(packet) > MAX_CREDENTIAL_PACKET_BYTES:
        raise C01ProtocolError("credential_packet_invalid")
    return C01LaunchRequest(
        run_nonce=nonce,
        parent_pid=parent_pid,
        expected_worker_source_sha256=source_sha256,
        pair_binding=_parse_pair_binding(value["pair_binding"]),
        account_scope_sha256=account_scope_sha256,
        credential_binding_sha256=credential_binding_sha256,
        credential_packet=packet,
    )


def _validate_private_input(value: Mapping[str, Any]) -> C01PrivateInput:
    expected_keys = (
        "protocol",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
        "product_info",
        "native_flow_directory",
        "evidence_directory",
    )
    _exact_keys(value, expected_keys, "private_input")
    if value["protocol"] != PRIVATE_INPUT_PROTOCOL:
        raise C01ProtocolError("private_input_protocol_invalid")
    fields = {}
    for field in ("broker_id", "user_id", "password", "app_id", "auth_code"):
        fields[field] = _string(value[field], "private_input_" + field)
        if len(fields[field]) > 4096 or "\x00" in fields[field]:
            raise C01ProtocolError("private_input_" + field + "_invalid")
    fields["product_info"] = _string(
        value["product_info"], "private_input_product_info", nonempty=False
    )
    if len(fields["product_info"]) > 4096 or "\x00" in fields["product_info"]:
        raise C01ProtocolError("private_input_product_info_invalid")
    for field in ("native_flow_directory", "evidence_directory"):
        path = _string(value[field], "private_input_" + field)
        if len(path) > 32768 or "\x00" in path or not ntpath.isabs(path):
            raise C01ProtocolError("private_input_" + field + "_invalid")
        if any(part == ".." for part in re.split(r"[\\/]+", path)):
            raise C01ProtocolError("private_input_" + field + "_invalid")
        fields[field] = path
    if ntpath.normcase(ntpath.normpath(fields["native_flow_directory"])) == ntpath.normcase(
        ntpath.normpath(fields["evidence_directory"])
    ):
        raise C01ProtocolError("private_input_directories_must_be_distinct")
    return C01PrivateInput(**fields)


def encode_private_input_packet(value: C01PrivateInput) -> bytes:
    """Encode the worker-only private input envelope without exposing its repr."""

    if not isinstance(value, C01PrivateInput):
        raise C01ProtocolError("private_input_type_invalid")
    payload = {
        "protocol": PRIVATE_INPUT_PROTOCOL,
        "broker_id": value.broker_id,
        "user_id": value.user_id,
        "password": value.password,
        "app_id": value.app_id,
        "auth_code": value.auth_code,
        "product_info": value.product_info,
        "native_flow_directory": value.native_flow_directory,
        "evidence_directory": value.evidence_directory,
    }
    _validate_private_input(payload)
    return _encode_json_line(payload, limit=MAX_CREDENTIAL_PACKET_BYTES)


def parse_private_input_packet(frame: bytes) -> C01PrivateInput:
    """Worker-side parser; pair and account refs remain only in the outer frame."""

    value = _parse_frame(frame, limit=MAX_CREDENTIAL_PACKET_BYTES)
    return _validate_private_input(value)


def _validate_worker_shape(value: Dict[str, Any]) -> None:
    _exact_keys(
        value,
        (
            "protocol",
            "message_type",
            "version",
            "case_id",
            "run_nonce",
            "parent_pid",
            "worker_pid",
            "worker_source_sha256",
            "pair_binding",
            "account_scope_sha256",
            "credential_binding_sha256",
            "client",
            "requests",
            "callbacks",
            "snapshots",
            "write_counters",
            "native_close",
            "terminal_state",
        ),
        "worker",
    )
    if (
        value["protocol"] != PROTOCOL_NAME
        or value["message_type"] != WORKER_MESSAGE
        or type(value["version"]) is not int
        or value["version"] != PROTOCOL_VERSION
        or value["case_id"] != "C01"
        or value["terminal_state"] != "normal"
    ):
        raise C01ProtocolError("worker_identity_invalid")
    nonce = _string(value["run_nonce"], "run_nonce")
    if not _HEX_32_RE.fullmatch(nonce):
        raise C01ProtocolError("run_nonce_invalid")
    parent_pid = _int(value["parent_pid"], "parent_pid", minimum=1)
    worker_pid = _int(value["worker_pid"], "worker_pid", minimum=1)
    if worker_pid == parent_pid:
        raise C01ProtocolError("worker_pid_invalid")
    _digest(value["worker_source_sha256"], "worker_source_sha256")
    _parse_pair_ref(value["pair_binding"])
    account_scope_sha256 = _digest(value["account_scope_sha256"], "account_scope_sha256")
    credential_binding_sha256 = _digest(
        value["credential_binding_sha256"], "credential_binding_sha256"
    )

    client = value["client"]
    if not isinstance(client, dict):
        raise C01ProtocolError("client_invalid")
    _exact_keys(client, ("instance_id", "client_generation", "arrival_generation"), "client")
    _string(client["instance_id"], "client_instance_id")
    _int(client["client_generation"], "client_generation", minimum=1)
    _int(client["arrival_generation"], "arrival_generation", minimum=1)

    requests = value["requests"]
    if not isinstance(requests, list) or len(requests) != 8:
        raise C01ProtocolError("requests_invalid")
    request_keys = (
        "kind",
        "phase",
        "family",
        "method",
        "request_id",
        "request_generation",
        "local_sequence",
        "issued_at_utc",
        "issued_monotonic_ns",
        "return_code",
        "sdk_query_result",
        "receipt_origin",
        "account_scope_sha256",
        "credential_binding_sha256",
    )
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            raise C01ProtocolError("request_invalid")
        _exact_keys(request, request_keys, "request")
        kind = _string(request["kind"], "request_kind")
        phase = request["phase"]
        family = request["family"]
        if index < 2:
            expected_kind = ("authenticate", "login")[index]
            expected_method = ("ReqAuthenticate", "ReqUserLogin")[index]
            if kind != expected_kind or phase is not None or family is not None:
                raise C01ProtocolError("auth_login_request_scope_invalid")
            if request["method"] != expected_method:
                raise C01ProtocolError("auth_login_method_invalid")
        else:
            offset = index - 2
            expected_phase = "baseline" if offset < 3 else "final"
            expected_family = ("orders", "positions", "funds")[offset % 3]
            if (
                kind != "query"
                or not isinstance(phase, str)
                or not isinstance(family, str)
                or phase != expected_phase
                or family != expected_family
            ):
                raise C01ProtocolError("query_request_scope_invalid")
            if request["method"] != _QUERY_METHODS[expected_family][0]:
                raise C01ProtocolError("query_method_invalid")
        _int(request["request_id"], "request_id", minimum=1)
        _int(request["request_generation"], "request_generation", minimum=1)
        _int(request["local_sequence"], "request_local_sequence", minimum=1)
        _utc(request["issued_at_utc"], "request_issued_at_utc")
        _int(request["issued_monotonic_ns"], "request_issued_monotonic_ns", minimum=1)
        _nullable_int(request["return_code"], "request_return_code", minimum=0)
        if request["receipt_origin"] != "local_native_invocation":
            raise C01ProtocolError("request_receipt_origin_invalid")
        if request["account_scope_sha256"] != account_scope_sha256:
            raise C01ProtocolError("request_account_scope_mismatch")
        if request["credential_binding_sha256"] != credential_binding_sha256:
            raise C01ProtocolError("request_credential_binding_mismatch")
        if kind == "query":
            _validate_sdk_query_result(request["sdk_query_result"], request, client)
        elif request["sdk_query_result"] is not None:
            raise C01ProtocolError("auth_login_has_sdk_query_result")

    callbacks = value["callbacks"]
    if not isinstance(callbacks, list) or not 8 <= len(callbacks) <= MAX_CALLBACKS:
        raise C01ProtocolError("callbacks_invalid")
    callback_keys = (
        "kind",
        "phase",
        "family",
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "front_id",
        "session_id",
        "trading_day",
        "account_scope_sha256",
        "credential_binding_sha256",
    )
    for callback in callbacks:
        if not isinstance(callback, dict):
            raise C01ProtocolError("callback_invalid")
        _exact_keys(callback, callback_keys, "callback")
        kind = _string(callback["kind"], "callback_kind")
        name = _string(callback["callback_name"], "callback_name")
        if kind not in _CALLBACK_KINDS or name not in _CALLBACK_NAMES:
            raise C01ProtocolError("callback_kind_or_name_invalid")
        phase = callback["phase"]
        family = callback["family"]
        if kind == "query":
            if (
                not isinstance(phase, str)
                or not isinstance(family, str)
                or phase not in _PHASES
                or family not in _FAMILIES
            ):
                raise C01ProtocolError("query_callback_scope_invalid")
            expected_name = _QUERY_METHODS[family][1]
            if name != expected_name:
                raise C01ProtocolError("query_callback_name_invalid")
            if type(callback["row_present"]) is not bool:
                raise C01ProtocolError("query_callback_row_flag_invalid")
            _int(callback["request_id"], "callback_request_id", minimum=1)
            _validate_callback_error_facts(callback, required=True)
            _bool(callback["is_last"], "callback_is_last")
            _int(callback["request_generation"], "callback_request_generation", minimum=1)
        elif kind in ("authenticate", "login"):
            expected_name = "OnRspAuthenticate" if kind == "authenticate" else "OnRspUserLogin"
            if name != expected_name or phase is not None or family is not None:
                raise C01ProtocolError("auth_login_callback_scope_invalid")
            if callback["row_present"] is not None:
                raise C01ProtocolError("auth_login_row_flag_invalid")
            _int(callback["request_id"], "callback_request_id", minimum=1)
            _validate_callback_error_facts(callback, required=True)
            if callback["rsp_info_present"] is not True:
                raise C01ProtocolError("auth_login_rsp_info_required")
            _bool(callback["is_last"], "callback_is_last")
            _int(callback["request_generation"], "callback_request_generation", minimum=1)
        else:
            expected_name = "OnRtnOrder" if kind == "order_activity" else "OnRtnTrade"
            if name != expected_name or phase is not None or family is not None:
                raise C01ProtocolError("activity_callback_scope_invalid")
            if any(
                callback[field] is not None
                for field in (
                    "request_id",
                    "error_id",
                    "rsp_info_present",
                    "error_semantics",
                    "is_last",
                    "request_generation",
                    "row_present",
                )
            ):
                raise C01ProtocolError("activity_callback_has_response_fields")
            _validate_callback_error_facts(callback, required=False)
        if callback["client_instance_id"] != client["instance_id"]:
            raise C01ProtocolError("callback_client_identity_invalid")
        if callback["client_generation"] != client["client_generation"]:
            raise C01ProtocolError("callback_client_generation_invalid")
        if callback["arrival_generation"] != client["arrival_generation"]:
            raise C01ProtocolError("callback_arrival_generation_invalid")
        if callback["account_scope_sha256"] != account_scope_sha256:
            raise C01ProtocolError("callback_account_scope_mismatch")
        if callback["credential_binding_sha256"] != credential_binding_sha256:
            raise C01ProtocolError("callback_credential_binding_mismatch")
        _int(callback["local_sequence"], "callback_local_sequence", minimum=1)
        _utc(callback["arrived_at_utc"], "callback_arrived_at_utc")
        _int(callback["arrived_monotonic_ns"], "callback_arrived_monotonic_ns", minimum=1)
        if kind == "login":
            _int(callback["front_id"], "login_front_id", minimum=1)
            _string(callback["session_id"], "login_session_id")
            trading_day = _string(callback["trading_day"], "login_trading_day")
            if not re.fullmatch(r"\d{8}", trading_day):
                raise C01ProtocolError("login_trading_day_invalid")
        elif any(
            callback[field] is not None for field in ("front_id", "session_id", "trading_day")
        ):
            raise C01ProtocolError("non_login_callback_has_login_facts")

    snapshots = value["snapshots"]
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        raise C01ProtocolError("snapshots_invalid")
    snapshot_keys = (
        "phase",
        "artifact_ref",
        "artifact_sha256",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "session_id",
        "trading_day",
        "queries",
        "open_order_refs_sha256",
        "order_economics_sha256",
        "positions_sha256",
        "funds_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
    )
    for snapshot, expected_phase, expected_ref in zip(
        snapshots, ("baseline", "final"), ("snapshots/baseline.json", "snapshots/final.json")
    ):
        if not isinstance(snapshot, dict):
            raise C01ProtocolError("snapshot_invalid")
        _exact_keys(snapshot, snapshot_keys, "snapshot")
        if snapshot["phase"] != expected_phase or snapshot["artifact_ref"] != expected_ref:
            raise C01ProtocolError("snapshot_scope_invalid")
        _digest(snapshot["artifact_sha256"], "snapshot_artifact_sha256")
        _string(snapshot["client_instance_id"], "snapshot_client_instance_id")
        _int(snapshot["client_generation"], "snapshot_client_generation", minimum=1)
        _int(snapshot["arrival_generation"], "snapshot_arrival_generation", minimum=1)
        _string(snapshot["session_id"], "snapshot_session_id")
        trading_day = _string(snapshot["trading_day"], "snapshot_trading_day")
        if not re.fullmatch(r"\d{8}", trading_day):
            raise C01ProtocolError("snapshot_trading_day_invalid")
        queries = snapshot["queries"]
        if not isinstance(queries, dict) or set(queries) != _FAMILIES:
            raise C01ProtocolError("snapshot_queries_invalid")
        for family, query in queries.items():
            if not isinstance(query, dict):
                raise C01ProtocolError("snapshot_query_invalid")
            _exact_keys(
                query,
                (
                    "request_id",
                    "callback_count",
                    "row_count",
                    "first_sequence",
                    "terminal_sequence",
                ),
                "snapshot_query",
            )
            _int(query["request_id"], "snapshot_query_request_id", minimum=1)
            _int(query["callback_count"], "snapshot_query_callback_count", minimum=1)
            _int(query["row_count"], "snapshot_query_row_count", minimum=0)
            _int(query["first_sequence"], "snapshot_query_first_sequence", minimum=1)
            _int(query["terminal_sequence"], "snapshot_query_terminal_sequence", minimum=1)
        _digest(snapshot["open_order_refs_sha256"], "open_order_refs_sha256")
        _digest(snapshot["order_economics_sha256"], "order_economics_sha256")
        _digest(snapshot["positions_sha256"], "positions_sha256")
        _digest(snapshot["funds_sha256"], "funds_sha256")
        if snapshot["account_scope_sha256"] != account_scope_sha256:
            raise C01ProtocolError("snapshot_account_scope_mismatch")
        if snapshot["credential_binding_sha256"] != credential_binding_sha256:
            raise C01ProtocolError("snapshot_credential_binding_mismatch")

    write_counters = value["write_counters"]
    if not isinstance(write_counters, dict):
        raise C01ProtocolError("write_counters_invalid")
    _exact_keys(write_counters, ("ReqOrderInsert", "ReqOrderAction"), "write_counters")
    for name, count in write_counters.items():
        _int(count, "write_counter_" + name, minimum=0)

    native_close = value["native_close"]
    if not isinstance(native_close, dict):
        raise C01ProtocolError("native_close_invalid")
    _exact_keys(
        native_close,
        (
            "receipt_type",
            "lifecycle_mode",
            "join_required",
            "join_completed",
            "native_released",
            "thread_alive",
            "timed_out",
        ),
        "native_close",
    )
    if native_close["receipt_type"] != "CtpNativeStopReceipt":
        raise C01ProtocolError("native_close_receipt_type_invalid")
    if native_close["lifecycle_mode"] != "NO_JOIN_RELEASE_RETURNED":
        raise C01ProtocolError("native_close_lifecycle_mode_invalid")
    for field in ("join_required", "join_completed", "native_released", "timed_out"):
        _bool(native_close[field], "native_close_" + field)
    _nullable_bool(native_close["thread_alive"], "native_close_thread_alive")
    if (
        native_close["join_required"] is not False
        or native_close["join_completed"] is not True
        or native_close["native_released"] is not True
        or native_close["thread_alive"] is not False
        or native_close["timed_out"] is not False
    ):
        raise C01ProtocolError("native_close_no_join_release_incomplete")


def encode_worker_frame(payload: Mapping[str, Any]) -> bytes:
    """Encode one strict child receipt line after validating its fixed schema."""

    if not isinstance(payload, Mapping):
        raise C01ProtocolError("worker_payload_invalid")
    value = _thaw(payload)
    if not isinstance(value, dict):
        raise C01ProtocolError("worker_payload_invalid")
    _validate_worker_shape(value)
    return _encode_json_line(value, limit=MAX_WORKER_FRAME_BYTES)


def parse_worker_frame(frame: bytes) -> C01WorkerReceipt:
    """Parse one bounded child receipt; process facts are validated separately."""

    value = _parse_frame(frame, limit=MAX_WORKER_FRAME_BYTES)
    _validate_worker_shape(value)
    return C01WorkerReceipt(payload=_freeze(value))


def sha256_bytes(value: bytes) -> str:
    """Small helper shared by inert protocol tests and parent source pinning."""

    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Return compact deterministic UTF-8 JSON without a line terminator."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise C01ProtocolError("value_not_canonical_json_safe") from None


def canonical_value_sha256(value: Any) -> str:
    """SHA-256 over ``canonical_json_bytes(value)`` (no trailing newline)."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def compute_account_scope_sha256(broker_id: str, user_id: str) -> str:
    """Compute the private account-scope reference from exact input values."""

    if not isinstance(broker_id, str) or not broker_id:
        raise C01ProtocolError("broker_id_invalid")
    if not isinstance(user_id, str) or not user_id:
        raise C01ProtocolError("user_id_invalid")
    return canonical_value_sha256(
        {"scheme": ACCOUNT_SCOPE_SCHEME, "broker_id": broker_id, "user_id": user_id}
    )


def compute_credential_binding_sha256(
    broker_id: str,
    user_id: str,
    password: str,
    app_id: str,
    auth_code: str,
    product_info: str,
) -> str:
    """Compute the private credential binding; never log the value or digest."""

    values = {
        "broker_id": broker_id,
        "user_id": user_id,
        "password": password,
        "app_id": app_id,
        "auth_code": auth_code,
        "product_info": product_info,
    }
    if any(not isinstance(value, str) for value in values.values()):
        raise C01ProtocolError("credential_binding_input_invalid")
    if any(
        not values[field] for field in ("broker_id", "user_id", "password", "app_id", "auth_code")
    ):
        raise C01ProtocolError("credential_binding_input_incomplete")
    return canonical_value_sha256({"scheme": CREDENTIAL_BINDING_SCHEME, **values})


def _decimal_string(value: Any, where: str, *, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise C01ProtocolError(where + "_invalid")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise C01ProtocolError(where + "_invalid") from None
    if (
        not number.is_finite()
        or (nonnegative and number < 0)
        or number.copy_abs() >= Decimal("1e30")
    ):
        raise C01ProtocolError(where + "_invalid")
    sign, raw_digits, exponent = number.as_tuple()
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if len(digits) > 64 or max(0, -exponent) > 18:
        raise C01ProtocolError(where + "_invalid")
    if not digits:
        rendered = "0"
    else:
        text = "".join(str(digit) for digit in digits)
        if exponent >= 0:
            rendered = text + ("0" * exponent)
        else:
            point = len(text) + exponent
            if point <= 0:
                rendered = "0." + ("0" * -point) + text
            else:
                rendered = text[:point] + "." + text[point:]
        if sign:
            rendered = "-" + rendered
    if len(rendered) > 128 or rendered != value:
        raise C01ProtocolError(where + "_not_canonical")
    return number


def canonical_decimal_text(value: Any) -> str:
    """Normalize a JSON scalar to a finite exact base-10 decimal string."""

    if type(value) not in (str, int, float):
        raise C01ProtocolError("decimal_value_invalid")
    input_text = str(value)
    if len(input_text) > 128:
        raise C01ProtocolError("decimal_value_invalid")
    if input_text != input_text.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in input_text
    ):
        raise C01ProtocolError("decimal_value_invalid")
    try:
        number = Decimal(input_text)
    except InvalidOperation:
        raise C01ProtocolError("decimal_value_invalid") from None
    if not number.is_finite() or number.copy_abs() >= Decimal("1e30"):
        raise C01ProtocolError("decimal_value_invalid")
    sign, raw_digits, exponent = number.as_tuple()
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if len(digits) > 64 or max(0, -exponent) > 18:
        raise C01ProtocolError("decimal_value_invalid")
    if not digits:
        return "0"
    text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        rendered = text + ("0" * exponent)
    else:
        point = len(text) + exponent
        rendered = "0." + ("0" * -point) + text if point <= 0 else text[:point] + "." + text[point:]
    if sign:
        rendered = "-" + rendered
    if len(rendered) > 128:
        raise C01ProtocolError("decimal_value_invalid")
    return rendered


def _bounded_artifact_text(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or len(value) > 128
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        raise C01ProtocolError(where + "_invalid")
    return value


def _validate_biz_type_tag(value: Any, where: str) -> None:
    if type(value) is not dict or not isinstance(value.get("state"), str):
        raise C01ProtocolError(where + "_invalid")
    if value["state"] == "unknown":
        _exact_keys(value, ("state", "reason"), where)
        if value["reason"] != "nul_only":
            raise C01ProtocolError(where + "_invalid")
        return
    if value["state"] == "observed":
        _exact_keys(value, ("state", "value"), where)
        text = value["value"]
        if (
            type(text) is not str
            or not text
            or len(text) > 128
            or text != text.strip()
            or any(unicodedata.category(char) == "Cc" for char in text)
        ):
            raise C01ProtocolError(where + "_invalid")
        return
    raise C01ProtocolError(where + "_invalid")


def parse_private_snapshot_artifact(frame: bytes) -> C01PrivateSnapshot:
    """Parse and validate one canonical, bounded private C01 snapshot artifact.

    This is an in-memory byte validator only.  It does not open files or prove
    ACL, owner, reparse-point, path, or saved-artifact custody.
    """

    value = _parse_frame(frame, limit=MAX_PRIVATE_SNAPSHOT_BYTES)
    try:
        canonical = canonical_json_bytes(value) + b"\n"
    except C01ProtocolError:
        raise
    if frame != canonical:
        raise C01ProtocolError("private_snapshot_not_canonical")
    _exact_keys(
        value,
        (
            "protocol",
            "version",
            "case_id",
            "phase",
            "account_scope_sha256",
            "credential_binding_sha256",
            "client",
            "scope",
            "queries",
            "projections",
        ),
        "private_snapshot",
    )
    if (
        value["protocol"] != PROTOCOL_NAME
        or type(value["version"]) is not int
        or value["version"] != PROTOCOL_VERSION
        or value["case_id"] != "C01"
        or not isinstance(value["phase"], str)
        or value["phase"] not in _PHASES
    ):
        raise C01ProtocolError("private_snapshot_identity_invalid")
    _digest(value["account_scope_sha256"], "snapshot_account_scope_sha256")
    _digest(value["credential_binding_sha256"], "snapshot_credential_binding_sha256")

    client = value["client"]
    if not isinstance(client, dict):
        raise C01ProtocolError("private_snapshot_client_invalid")
    _exact_keys(
        client, ("instance_id", "client_generation", "arrival_generation"), "snapshot_client"
    )
    _string(client["instance_id"], "snapshot_client_instance_id")
    _int(client["client_generation"], "snapshot_client_generation", minimum=1)
    _int(client["arrival_generation"], "snapshot_arrival_generation", minimum=1)

    scope = value["scope"]
    if not isinstance(scope, dict):
        raise C01ProtocolError("private_snapshot_scope_invalid")
    _exact_keys(scope, ("front_id", "session_id", "trading_day"), "snapshot_scope")
    _int(scope["front_id"], "snapshot_front_id", minimum=1)
    _string(scope["session_id"], "snapshot_session_id")
    trading_day = _string(scope["trading_day"], "snapshot_trading_day")
    if not re.fullmatch(r"\d{8}", trading_day):
        raise C01ProtocolError("snapshot_trading_day_invalid")

    queries = value["queries"]
    if not isinstance(queries, dict) or set(queries) != _FAMILIES:
        raise C01ProtocolError("private_snapshot_queries_invalid")
    artifact_request_keys = (
        "method",
        "request_id",
        "request_generation",
        "local_sequence",
        "issued_at_utc",
        "issued_monotonic_ns",
        "return_code",
        "sdk_query_result",
    )
    artifact_callback_keys = (
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "row",
    )
    query_identity_bindings = set()
    query_account_fingerprints = set()
    for family in ("orders", "positions", "funds"):
        query = queries[family]
        if not isinstance(query, dict):
            raise C01ProtocolError("private_snapshot_query_invalid")
        _exact_keys(query, ("request", "callbacks"), "private_snapshot_query")
        request = query["request"]
        if not isinstance(request, dict):
            raise C01ProtocolError("private_snapshot_query_request_invalid")
        _exact_keys(request, artifact_request_keys, "private_snapshot_query_request")
        if request["method"] != _QUERY_METHODS[family][0]:
            raise C01ProtocolError("private_snapshot_query_method_invalid")
        _int(request["request_id"], "snapshot_request_id", minimum=1)
        _int(request["request_generation"], "snapshot_request_generation", minimum=1)
        _int(request["local_sequence"], "snapshot_request_sequence", minimum=1)
        _utc(request["issued_at_utc"], "snapshot_request_issued_at_utc")
        _int(request["issued_monotonic_ns"], "snapshot_request_issued_monotonic_ns", minimum=1)
        _nullable_int(request["return_code"], "snapshot_request_return_code", minimum=0)
        _validate_sdk_query_result(
            request["sdk_query_result"], {**request, "family": family}, client
        )
        callbacks = query["callbacks"]
        if not isinstance(callbacks, list) or not 1 <= len(callbacks) <= MAX_CALLBACKS:
            raise C01ProtocolError("private_snapshot_query_callbacks_invalid")
        prior_sequence = request["local_sequence"]
        for index, callback in enumerate(callbacks):
            if not isinstance(callback, dict):
                raise C01ProtocolError("private_snapshot_callback_invalid")
            _exact_keys(callback, artifact_callback_keys, "private_snapshot_callback")
            if callback["callback_name"] != _QUERY_METHODS[family][1]:
                raise C01ProtocolError("private_snapshot_callback_name_invalid")
            if callback["request_id"] != request["request_id"]:
                raise C01ProtocolError("private_snapshot_callback_request_id_mismatch")
            if callback["request_generation"] != request["request_generation"]:
                raise C01ProtocolError("private_snapshot_callback_generation_mismatch")
            _validate_callback_error_facts(callback, required=True)
            if callback["is_last"] is not (index == len(callbacks) - 1):
                raise C01ProtocolError("private_snapshot_callback_terminal_order_invalid")
            sequence = _int(callback["local_sequence"], "snapshot_callback_sequence", minimum=1)
            if sequence <= prior_sequence:
                raise C01ProtocolError("private_snapshot_callback_sequence_invalid")
            prior_sequence = sequence
            _utc(callback["arrived_at_utc"], "snapshot_callback_arrived_at_utc")
            _int(
                callback["arrived_monotonic_ns"],
                "snapshot_callback_arrived_monotonic_ns",
                minimum=1,
            )
            if type(callback["row_present"]) is not bool:
                raise C01ProtocolError("private_snapshot_callback_row_flag_invalid")
            row = callback["row"]
            if callback["row_present"]:
                if not isinstance(row, dict) or any(type(key) is not str for key in row):
                    raise C01ProtocolError("private_snapshot_callback_row_invalid")
                if any(
                    item is not None and type(item) not in (bool, int, float, str)
                    for item in row.values()
                ):
                    raise C01ProtocolError("private_snapshot_callback_row_value_invalid")
            elif row is not None:
                raise C01ProtocolError("private_snapshot_callback_missing_row_invalid")

        sdk_result = request["sdk_query_result"]
        query_source = sdk_result["query_source"]
        if query_source["trading_day"] != trading_day:
            raise C01ProtocolError("private_snapshot_query_source_trading_day_mismatch")
        query_identity_bindings.add(
            (query_source["broker_id"], query_source["investor_id"], query_source["trading_day"])
        )
        query_account_fingerprints.add(query_source["account_fingerprint"])
        detached_rows = [item["row"] for item in callbacks if item["row_present"] is True]
        if sdk_result["record_count"] != len(detached_rows):
            raise C01ProtocolError("private_snapshot_query_result_record_count_mismatch")
        callback_digest = canonical_sdk_query_records_sha256(detached_rows)
        if (
            callback_digest != sdk_result["callback_records_sha256"]
            or callback_digest != sdk_result["records_sha256"]
            or callback_digest != query_source["records_sha256"]
        ):
            raise C01ProtocolError("private_snapshot_query_record_content_mismatch")

    if len(query_identity_bindings) != 1 or len(query_account_fingerprints) != 1:
        raise C01ProtocolError("private_snapshot_query_source_scope_inconsistent")

    projections = value["projections"]
    if not isinstance(projections, dict) or set(projections) != {
        "open_order_refs",
        "order_economics",
        "positions",
        "funds",
    }:
        raise C01ProtocolError("private_snapshot_projections_invalid")
    order_refs = projections["open_order_refs"]
    if not isinstance(order_refs, list):
        raise C01ProtocolError("private_snapshot_order_refs_invalid")
    encoded_order_refs = []
    for ref in order_refs:
        if not isinstance(ref, dict):
            raise C01ProtocolError("private_snapshot_order_ref_invalid")
        kind = ref.get("kind")
        if kind == "ctp_order_sys_id":
            _exact_keys(ref, ("kind", "exchange_id", "order_sys_id"), "snapshot_order_ref")
            _bounded_artifact_text(ref["exchange_id"], "snapshot_order_ref_exchange_id")
            _bounded_artifact_text(ref["order_sys_id"], "snapshot_order_ref_order_sys_id")
        elif kind == "ctp_front_session_order_ref":
            _exact_keys(ref, ("kind", "front_id", "session_id", "order_ref"), "snapshot_order_ref")
            _int(ref["front_id"], "snapshot_order_ref_front_id", minimum=1)
            _int(ref["session_id"], "snapshot_order_ref_session_id", minimum=1)
            _bounded_artifact_text(ref["order_ref"], "snapshot_order_ref_order_ref")
        else:
            raise C01ProtocolError("private_snapshot_order_ref_kind_invalid")
        encoded_order_refs.append(canonical_json_bytes(ref))
    if encoded_order_refs != sorted(set(encoded_order_refs)):
        raise C01ProtocolError("private_snapshot_order_refs_not_unique_sorted")

    order_economics = projections["order_economics"]
    if not isinstance(order_economics, dict):
        raise C01ProtocolError("private_snapshot_order_economics_invalid")
    _exact_keys(
        order_economics,
        ("schema", "rows"),
        "snapshot_order_economics",
    )
    if order_economics["schema"] != ORDER_ECONOMICS_SCHEMA:
        raise C01ProtocolError("snapshot_order_economics_schema_invalid")
    order_rows = order_economics["rows"]
    if not isinstance(order_rows, list) or len(order_rows) > MAX_CALLBACKS:
        raise C01ProtocolError("snapshot_order_economics_rows_invalid")
    identity_text_allow_empty = {"ExchangeID", "OrderSysID", "OrderRef"}
    expected_order_measure_keys = (
        set(ORDER_DECIMAL_MEASURES) | set(ORDER_INTEGER_MEASURES) | set(ORDER_TEXT_MEASURES)
    )
    encoded_order_rows = []
    identity_tokens = set()
    for order_row in order_rows:
        if not isinstance(order_row, dict):
            raise C01ProtocolError("snapshot_order_economics_row_invalid")
        _exact_keys(order_row, ("identity", "measures"), "snapshot_order_economics_row")
        identity = order_row["identity"]
        if not isinstance(identity, dict):
            raise C01ProtocolError("snapshot_order_identity_invalid")
        _exact_keys(
            identity,
            ORDER_IDENTITY_TEXT_FIELDS + ORDER_IDENTITY_INTEGER_FIELDS,
            "snapshot_order_identity",
        )
        for field in ORDER_IDENTITY_TEXT_FIELDS:
            _bounded_artifact_text(
                identity[field],
                "snapshot_order_identity_" + field,
                allow_empty=field in identity_text_allow_empty,
            )
        for field in ORDER_IDENTITY_INTEGER_FIELDS:
            number = _int(identity[field], "snapshot_order_identity_" + field, minimum=0)
            if number >= 10**30:
                raise C01ProtocolError("snapshot_order_identity_integer_invalid")
        if identity["TradingDay"] != scope["trading_day"]:
            raise C01ProtocolError("snapshot_order_trading_day_mismatch")
        measures = order_row["measures"]
        if not isinstance(measures, dict):
            raise C01ProtocolError("snapshot_order_measures_invalid")
        _exact_keys(measures, tuple(expected_order_measure_keys), "snapshot_order_measures")
        for field in ORDER_DECIMAL_MEASURES:
            _decimal_string(measures[field], "snapshot_order_measure_" + field)
        for field in ORDER_INTEGER_MEASURES:
            number = _int(measures[field], "snapshot_order_measure_" + field, minimum=0)
            if number >= 10**30:
                raise C01ProtocolError("snapshot_order_measure_integer_invalid")
        for field in ORDER_TEXT_MEASURES:
            _bounded_artifact_text(measures[field], "snapshot_order_measure_" + field)
        identity_token = canonical_json_bytes(identity)
        if identity_token in identity_tokens:
            raise C01ProtocolError("snapshot_order_identity_duplicated")
        identity_tokens.add(identity_token)
        encoded_order_rows.append(canonical_json_bytes(order_row))
    if encoded_order_rows != sorted(encoded_order_rows):
        raise C01ProtocolError("snapshot_order_economics_rows_not_sorted")

    positions = projections["positions"]
    if not isinstance(positions, dict):
        raise C01ProtocolError("private_snapshot_positions_invalid")
    _exact_keys(positions, ("schema", "dimensions", "buckets"), "snapshot_positions")
    if positions["schema"] != POSITION_BUCKET_SCHEMA or positions["dimensions"] != list(
        POSITION_BUCKET_DIMENSIONS
    ):
        raise C01ProtocolError("private_snapshot_position_schema_invalid")
    buckets = positions["buckets"]
    if not isinstance(buckets, list):
        raise C01ProtocolError("private_snapshot_position_buckets_invalid")
    bucket_keys = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise C01ProtocolError("private_snapshot_position_bucket_invalid")
        _exact_keys(
            bucket,
            (
                "exchange_id",
                "instrument_id",
                "position_direction",
                "hedge_flag",
                "position_date",
                "quantity",
                "rows",
            ),
            "snapshot_position_bucket",
        )
        dimension_values = tuple(
            _bounded_artifact_text(bucket[field], "snapshot_position_dimension")
            for field in (
                "exchange_id",
                "instrument_id",
                "position_direction",
                "hedge_flag",
                "position_date",
            )
        )
        if dimension_values[0] not in KNOWN_CTP_EXCHANGES:
            raise C01ProtocolError("snapshot_position_exchange_invalid")
        if dimension_values[2] not in {"1", "2", "3"}:
            raise C01ProtocolError("snapshot_position_direction_invalid")
        if dimension_values[3] not in {"1", "2", "3"}:
            raise C01ProtocolError("snapshot_position_hedge_flag_invalid")
        if dimension_values[4] not in {"1", "2"}:
            raise C01ProtocolError("snapshot_position_date_invalid")
        _decimal_string(bucket["quantity"], "snapshot_position_quantity", nonnegative=True)
        rows = bucket["rows"]
        if not isinstance(rows, list) or not rows:
            raise C01ProtocolError("snapshot_position_measure_rows_invalid")
        expected_measure_keys = set(POSITION_NUMERIC_MEASURES) | set(POSITION_TEXT_MEASURES)
        normalized_rows = []
        quantity_sum = Decimal(0)
        with localcontext() as context:
            context.prec = 128
            for row in rows:
                if not isinstance(row, dict) or set(row) != expected_measure_keys:
                    raise C01ProtocolError("snapshot_position_measure_row_invalid")
                normalized = {}
                for field in POSITION_NUMERIC_MEASURES:
                    amount = _decimal_string(
                        row[field],
                        "snapshot_position_measure_" + field,
                        nonnegative=field in POSITION_NONNEGATIVE_MEASURES,
                    )
                    if field in POSITION_INTEGER_MEASURES and amount != amount.to_integral_value():
                        raise C01ProtocolError("snapshot_position_measure_fractional")
                    normalized[field] = row[field]
                for field in POSITION_TEXT_MEASURES:
                    normalized[field] = _bounded_artifact_text(
                        row[field],
                        "snapshot_position_measure_" + field,
                        allow_empty=field in {"InvestUnitID", "reserve1"},
                    )
                if normalized_rows and canonical_json_bytes(normalized) < normalized_rows[-1]:
                    raise C01ProtocolError("snapshot_position_measure_rows_not_sorted")
                normalized_rows.append(canonical_json_bytes(normalized))
                quantity_sum += _decimal_string(
                    row["Position"], "snapshot_position_row_quantity", nonnegative=True
                )
        if quantity_sum != _decimal_string(
            bucket["quantity"], "snapshot_position_quantity", nonnegative=True
        ):
            raise C01ProtocolError("snapshot_position_quantity_sum_mismatch")
        bucket_keys.append(dimension_values)
    if bucket_keys != sorted(bucket_keys) or len(bucket_keys) != len(set(bucket_keys)):
        raise C01ProtocolError("snapshot_position_buckets_not_unique_sorted")

    funds = projections["funds"]
    if not isinstance(funds, dict):
        raise C01ProtocolError("private_snapshot_funds_invalid")
    _exact_keys(
        funds,
        (
            "schema",
            "dimensions",
            "measures",
            "diagnostic_field_sources",
            "diagnostics",
        ),
        "snapshot_funds",
    )
    if funds["schema"] != ACCOUNT_ECONOMICS_SCHEMA:
        raise C01ProtocolError("snapshot_funds_schema_invalid")
    dimensions = funds["dimensions"]
    if not isinstance(dimensions, dict):
        raise C01ProtocolError("snapshot_funds_dimensions_invalid")
    _exact_keys(dimensions, ACCOUNT_DIMENSION_FIELDS, "snapshot_funds_dimensions")
    for field in ACCOUNT_DIMENSION_FIELDS:
        if field == "BizType":
            _validate_biz_type_tag(dimensions[field], "snapshot_funds_dimension_BizType")
        else:
            _bounded_artifact_text(dimensions[field], "snapshot_funds_dimension_" + field)
    if dimensions["TradingDay"] != scope["trading_day"]:
        raise C01ProtocolError("snapshot_funds_trading_day_mismatch")
    measures = funds["measures"]
    if not isinstance(measures, dict):
        raise C01ProtocolError("snapshot_funds_measures_invalid")
    _exact_keys(measures, ACCOUNT_NUMERIC_MEASURES, "snapshot_funds_measures")
    for field in ACCOUNT_NUMERIC_MEASURES:
        amount = _decimal_string(
            measures[field],
            "snapshot_funds_measure_" + field,
            nonnegative=field in ACCOUNT_NONNEGATIVE_MEASURES,
        )
        if field in ACCOUNT_INTEGER_MEASURES and amount != amount.to_integral_value():
            raise C01ProtocolError("snapshot_funds_measure_fractional")
    if funds["diagnostic_field_sources"] != ACCOUNT_DIAGNOSTIC_FIELD_SOURCES:
        raise C01ProtocolError("snapshot_funds_diagnostic_sources_invalid")
    diagnostics = funds["diagnostics"]
    if not isinstance(diagnostics, dict):
        raise C01ProtocolError("snapshot_funds_diagnostics_invalid")
    _exact_keys(diagnostics, tuple(ACCOUNT_DIAGNOSTIC_FIELD_SOURCES), "snapshot_funds_diagnostics")
    expected_diagnostics = {
        name: measures[source] for name, source in ACCOUNT_DIAGNOSTIC_FIELD_SOURCES.items()
    }
    if diagnostics != expected_diagnostics:
        raise C01ProtocolError("snapshot_funds_diagnostics_mismatch")

    return C01PrivateSnapshot(payload=_freeze(value))


def encode_private_snapshot_artifact(value: Mapping[str, Any]) -> bytes:
    """Canonicalize and fully validate one private snapshot artifact."""

    if not isinstance(value, Mapping):
        raise C01ProtocolError("private_snapshot_type_invalid")
    frame = canonical_json_bytes(value) + b"\n"
    parse_private_snapshot_artifact(frame)
    return frame
