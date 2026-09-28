"""Bounded, source-only snapshots for Trader SPI callback ingress.

This module deliberately has no dependency on the generated ``_ctp`` module,
SQLite, a client lifecycle, or an execution authority.  It defines the exact
current Trader SPI method inventory, conservative callback classifications,
an immutable redacted snapshot format, and a class-level wrapper installer.

The client integration must install a durable sink before native API creation
or SPI registration, bind the owner intent and source tags at registration,
persist each complete record before calling its prior handler, and poison the
source on incomplete capture or any ambiguous commit acknowledgement.  These
records are not provider receipts, account authority, or send grants.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from types import MappingProxyType
from typing import Any, Callable, Union

_MAX_ID_BYTES = 128
_MAX_STRING_BYTES = 2048
_MAX_RECORD_BYTES = 32 * 1024
_MAX_CALLBACK_ARGUMENTS = 8
_MAX_FLATTENED_FIELDS = 128
_MAX_MISSING_FIELDS = 128
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z", re.ASCII)
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MISSING_ATTRIBUTE = object()

CallbackScalar = Union[str, int, float, bool, None]


class CtpTraderCallbackClass(str, Enum):
    PRE_LOGIN = "PRE_LOGIN"
    ROUTEABLE = "ROUTEABLE"
    AUDIT_QUERY = "AUDIT_QUERY"
    AUDIT_INFORMATIONAL = "AUDIT_INFORMATIONAL"
    LIFECYCLE_POISON = "LIFECYCLE_POISON"
    UNSUPPORTED_FINANCIAL = "UNSUPPORTED_FINANCIAL"


class CtpTraderCallbackPhase(str, Enum):
    PRE_LOGIN = "PRE_LOGIN"
    ACTIVE = "ACTIVE"
    POISONED = "POISONED"


class CtpTraderCallbackDisposition(str, Enum):
    PRE_LOGIN_CANDIDATE = "PRE_LOGIN_CANDIDATE"
    ROUTEABLE = "ROUTEABLE"
    AUDIT_QUERY = "AUDIT_QUERY"
    AUDIT_INFORMATIONAL = "AUDIT_INFORMATIONAL"
    POISON = "POISON"


@dataclass(frozen=True)
class CtpTraderCallbackSourceTagsV2:
    """Opaque values captured from the exact SPI/API pair at registration."""

    source_instance_id: str
    native_client_epoch: str
    native_api_source_id: str
    native_spi_source_id: str
    native_api_generation: int
    connection_generation: int

    def __post_init__(self) -> None:
        for name in (
            "source_instance_id",
            "native_client_epoch",
            "native_api_source_id",
            "native_spi_source_id",
        ):
            _validate_id(name, getattr(self, name))
        _validate_exact_int("native_api_generation", self.native_api_generation, minimum=1)
        _validate_exact_int("connection_generation", self.connection_generation, minimum=0)


@dataclass(frozen=True)
class CtpTraderCallbackArgumentV2:
    """One positional callback slot without retaining native objects."""

    slot: int
    name: str
    present: bool
    scalar_captured: bool
    value: CallbackScalar | None

    def __post_init__(self) -> None:
        _validate_exact_int("callback argument slot", self.slot, minimum=0)
        _validate_argument_name(self.name)
        if type(self.present) is not bool or type(self.scalar_captured) is not bool:
            raise ValueError("invalid callback argument presence flags")
        if not self.present and (self.scalar_captured or self.value is not None):
            raise ValueError("absent callback argument cannot carry a value")
        if self.scalar_captured:
            _validate_scalar(self.value, label="callback argument")
        elif self.value is not None:
            raise ValueError("uncaptured callback argument cannot carry a value")


@dataclass(frozen=True)
class CtpTraderCallbackFieldValueV2:
    """A safe getter result; ``present`` distinguishes absent from zero/None."""

    present: bool
    value: CallbackScalar | None
    scalar_captured: bool = True

    def __post_init__(self) -> None:
        if type(self.present) is not bool or type(self.scalar_captured) is not bool:
            raise ValueError("invalid callback field presence flags")
        if not self.present and (self.scalar_captured or self.value is not None):
            raise ValueError("absent callback field cannot carry a value")
        if self.scalar_captured:
            _validate_scalar(self.value, label="callback field")
        elif self.value is not None:
            raise ValueError("uncaptured callback field cannot carry a value")


CallbackFieldEntryV2 = tuple[int, str, CtpTraderCallbackFieldValueV2]


@dataclass(frozen=True)
class CtpTraderCallbackSpecV2:
    """Fixed, reviewable policy for one generated callback method."""

    callback_class: CtpTraderCallbackClass
    argument_names: tuple[str, ...]
    expected_argument_count: int
    scalar_argument_slots: tuple[int, ...]
    safe_fields_by_slot: tuple[tuple[int, tuple[str, ...]], ...] = ()
    required_fields: tuple[tuple[int, str], ...] = ()
    active_phase_poison: bool = False
    requires_active_query_match: bool = False

    def __post_init__(self) -> None:
        if type(self.callback_class) is not CtpTraderCallbackClass:
            raise ValueError("invalid callback class")
        if type(self.argument_names) is not tuple or any(
            type(name) is not str for name in self.argument_names
        ):
            raise ValueError("callback argument names must be immutable strings")
        _validate_exact_int(
            "expected callback argument count", self.expected_argument_count, minimum=0
        )
        if self.expected_argument_count > _MAX_CALLBACK_ARGUMENTS:
            raise ValueError("too many callback argument slots")
        if len(self.argument_names) != self.expected_argument_count:
            raise ValueError("callback argument names do not match expected count")
        if len(set(self.argument_names)) != len(self.argument_names):
            raise ValueError("duplicate callback argument name")
        for name in self.argument_names:
            _validate_argument_name(name)
        if type(self.scalar_argument_slots) is not tuple or any(
            type(slot) is not int or slot < 0 or slot >= self.expected_argument_count
            for slot in self.scalar_argument_slots
        ):
            raise ValueError("invalid scalar callback argument slots")
        if len(set(self.scalar_argument_slots)) != len(self.scalar_argument_slots):
            raise ValueError("duplicate scalar callback argument slot")
        if type(self.safe_fields_by_slot) is not tuple:
            raise ValueError("safe callback fields must be immutable")
        seen: set[tuple[int, str]] = set()
        for entry in self.safe_fields_by_slot:
            if (
                type(entry) is not tuple
                or len(entry) != 2
                or type(entry[0]) is not int
                or entry[0] < 0
                or entry[0] >= self.expected_argument_count
                or type(entry[1]) is not tuple
            ):
                raise ValueError("invalid safe callback field specification")
            for field_name in entry[1]:
                _validate_field_name(field_name)
                key = (entry[0], field_name)
                if key in seen:
                    raise ValueError("duplicate safe callback field")
                seen.add(key)
        if type(self.required_fields) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not int
            or type(item[1]) is not str
            or (item[0], item[1]) not in seen
            for item in self.required_fields
        ):
            raise ValueError("required callback fields must be allowlisted")
        if (
            type(self.active_phase_poison) is not bool
            or type(self.requires_active_query_match) is not bool
        ):
            raise ValueError("invalid callback lifecycle policy")


@dataclass(frozen=True)
class CtpTraderCallbackIngressRecordV2:
    owner_intent_id: str
    callback_name: str
    callback_class: CtpTraderCallbackClass
    source_phase: CtpTraderCallbackPhase
    source_instance_id: str
    native_client_epoch: str
    native_api_source_id: str
    native_spi_source_id: str
    native_api_generation: int
    source_connection_generation: int
    connection_generation: int
    source_sequence: int
    callback_monotonic_ns: int
    callback_arguments: tuple[CtpTraderCallbackArgumentV2, ...]
    flattened_fields: tuple[CallbackFieldEntryV2, ...]
    capture_complete: bool
    missing_field_names: tuple[str, ...]
    canonical_sha256: str

    def __post_init__(self) -> None:
        _validate_id("owner intent id", self.owner_intent_id)
        if type(self.callback_name) is not str or self.callback_name not in CALLBACK_SPECS:
            raise ValueError("unknown Trader SPI callback")
        if type(self.callback_class) is not CtpTraderCallbackClass:
            raise ValueError("invalid callback class")
        if self.callback_class is not CALLBACK_SPECS[self.callback_name].callback_class:
            raise ValueError("callback class does not match inventory")
        if type(self.source_phase) is not CtpTraderCallbackPhase:
            raise ValueError("invalid source phase")
        for name in (
            "source_instance_id",
            "native_client_epoch",
            "native_api_source_id",
            "native_spi_source_id",
        ):
            _validate_id(name, getattr(self, name))
        _validate_exact_int("native_api_generation", self.native_api_generation, minimum=1)
        _validate_exact_int(
            "source connection generation", self.source_connection_generation, minimum=0
        )
        _validate_exact_int("connection_generation", self.connection_generation, minimum=0)
        if self.connection_generation < self.source_connection_generation:
            raise ValueError("callback connection generation predates SPI registration")
        _validate_exact_int("source sequence", self.source_sequence, minimum=1)
        _validate_exact_int("callback monotonic timestamp", self.callback_monotonic_ns, minimum=1)
        if (
            type(self.callback_arguments) is not tuple
            or len(self.callback_arguments) > _MAX_CALLBACK_ARGUMENTS
        ):
            raise ValueError("invalid callback argument snapshot")
        if any(type(item) is not CtpTraderCallbackArgumentV2 for item in self.callback_arguments):
            raise ValueError("invalid callback argument snapshot")
        if (
            len(self.callback_arguments)
            != CALLBACK_SPECS[self.callback_name].expected_argument_count
        ):
            raise ValueError("callback argument snapshot does not match fixed signature")
        if tuple(item.slot for item in self.callback_arguments) != tuple(
            range(len(self.callback_arguments))
        ):
            raise ValueError("callback argument slots must be ordered and contiguous")
        if any(
            item.name != CALLBACK_SPECS[self.callback_name].argument_names[item.slot]
            for item in self.callback_arguments
        ):
            raise ValueError("callback argument name does not match fixed signature")
        spec = CALLBACK_SPECS[self.callback_name]
        if any(
            item.scalar_captured and item.slot not in spec.scalar_argument_slots
            for item in self.callback_arguments
        ):
            raise ValueError("callback captured a scalar outside its fixed scalar slots")
        if any(
            item.scalar_captured
            and not _is_allowed_scalar_argument(self.callback_name, item.slot, item.value)
            for item in self.callback_arguments
        ):
            raise ValueError("callback scalar does not match its generated SWIG type")
        if self.capture_complete and any(
            not self.callback_arguments[slot].scalar_captured for slot in spec.scalar_argument_slots
        ):
            raise ValueError("complete callback record is missing a fixed scalar argument")
        if (
            type(self.flattened_fields) is not tuple
            or len(self.flattened_fields) > _MAX_FLATTENED_FIELDS
        ):
            raise ValueError("invalid flattened callback field snapshot")
        allowed_fields = {
            (slot, name)
            for slot, names in CALLBACK_SPECS[self.callback_name].safe_fields_by_slot
            for name in names
        }
        seen_fields: set[tuple[int, str]] = set()
        for entry in self.flattened_fields:
            if (
                type(entry) is not tuple
                or len(entry) != 3
                or type(entry[0]) is not int
                or type(entry[1]) is not str
                or type(entry[2]) is not CtpTraderCallbackFieldValueV2
            ):
                raise ValueError("invalid flattened callback field entry")
            key = (entry[0], entry[1])
            if key not in allowed_fields or key in seen_fields:
                raise ValueError("callback field is not allowlisted or is duplicated")
            state = entry[2]
            if state.scalar_captured and not _matches_safe_field_type(entry[1], state.value):
                raise ValueError("callback field value does not match its generated SWIG type")
            if self.capture_complete and state.present and not state.scalar_captured:
                raise ValueError("complete callback record contains a failed getter")
            seen_fields.add(key)
        if type(self.capture_complete) is not bool:
            raise ValueError("invalid callback capture completeness")
        if self.capture_complete:
            if seen_fields != allowed_fields:
                raise ValueError("complete callback record omitted an allowlisted field getter")
            flattened_states = {(slot, name): state for slot, name, state in self.flattened_fields}
            for slot, name in spec.required_fields:
                state = flattened_states.get((slot, name))
                if (
                    state is None
                    or not state.present
                    or not state.scalar_captured
                    or state.value is None
                ):
                    raise ValueError("complete callback record is missing a required getter")
        if (
            type(self.missing_field_names) is not tuple
            or len(self.missing_field_names) > _MAX_MISSING_FIELDS
        ):
            raise ValueError("invalid missing callback field list")
        for item in self.missing_field_names:
            if type(item) is not str or not item or len(item.encode("utf-8")) > 256:
                raise ValueError("invalid missing callback field name")
            if not _is_safe_missing_reason(item):
                raise ValueError("invalid missing callback field reason")
        if self.capture_complete and self.missing_field_names:
            raise ValueError("complete callback record cannot list missing fields")
        if not self.capture_complete and not self.missing_field_names:
            raise ValueError("incomplete callback record must explain its incompleteness")
        if type(self.canonical_sha256) is not str or not _DIGEST_PATTERN.fullmatch(
            self.canonical_sha256
        ):
            raise ValueError("invalid callback record digest")
        if _digest_payload(self._payload()) != self.canonical_sha256:
            raise ValueError("callback record digest mismatch")
        bounded_payload = self._payload()
        if len(_canonical_bytes(bounded_payload)) > _MAX_RECORD_BYTES:
            raise ValueError("callback record exceeds size limit")
        bounded_payload["digest"] = self.canonical_sha256
        if len(_canonical_bytes(bounded_payload)) > _MAX_RECORD_BYTES:
            raise ValueError("callback record including digest exceeds size limit")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "ctp_trader_callback_ingress.v2",
            "owner_intent_id": self.owner_intent_id,
            "callback_name": self.callback_name,
            "callback_class": self.callback_class.value,
            "phase": self.source_phase.value,
            "source_instance_id": self.source_instance_id,
            "native_client_epoch": self.native_client_epoch,
            "native_api_source_id": self.native_api_source_id,
            "native_spi_source_id": self.native_spi_source_id,
            "native_api_generation": self.native_api_generation,
            "source_connection_generation": self.source_connection_generation,
            "connection_generation": self.connection_generation,
            "sequence": self.source_sequence,
            "monotonic_ns": self.callback_monotonic_ns,
            "named_args": [
                {
                    "argument_slot": item.slot,
                    "name": item.name,
                    "present": item.present,
                    "scalar_captured": item.scalar_captured,
                    "value": item.value,
                }
                for item in self.callback_arguments
            ],
            "flattened_fields": [
                {
                    "argument_slot": slot,
                    "field_name": name,
                    "present": state.present,
                    "scalar_captured": state.scalar_captured,
                    "value": state.value,
                }
                for slot, name, state in self.flattened_fields
            ],
            "capture_complete": self.capture_complete,
            "missing_getters": list(self.missing_field_names),
        }

    def to_payload(self) -> dict[str, Any]:
        """Return a fresh payload mapping with its digest included."""

        payload = self._payload()
        payload["digest"] = self.canonical_sha256
        return payload

    @property
    def digest(self) -> str:
        return self.canonical_sha256

    @property
    def phase(self) -> CtpTraderCallbackPhase:
        return self.source_phase

    @property
    def sequence(self) -> int:
        return self.source_sequence

    @property
    def monotonic_ns(self) -> int:
        return self.callback_monotonic_ns

    @property
    def missing_getters(self) -> tuple[str, ...]:
        return self.missing_field_names

    @property
    def named_args(self) -> tuple[CtpTraderCallbackArgumentV2, ...]:
        return self.callback_arguments

    def canonical_bytes(self) -> bytes:
        """Return canonical UTF-8 JSON bytes, including the record digest."""

        return _canonical_bytes(self.to_payload())

    def field_value(
        self, argument_slot: int, field_name: str
    ) -> CtpTraderCallbackFieldValueV2 | None:
        return next(
            (
                value
                for slot, name, value in self.flattened_fields
                if slot == argument_slot and name == field_name
            ),
            None,
        )

    def scalar_argument(self, slot: int) -> CallbackScalar | None:
        item = next((entry for entry in self.callback_arguments if entry.slot == slot), None)
        return item.value if item is not None and item.scalar_captured else None


@dataclass(frozen=True)
class CtpTraderCallbackIngressAckV2:
    owner_id: str
    sequence: int
    digest: str
    commit_state: str
    high_watermark: int

    def __post_init__(self) -> None:
        _validate_id("ack owner intent id", self.owner_id)
        _validate_exact_int("ack source sequence", self.sequence, minimum=1)
        if type(self.digest) is not str or not _DIGEST_PATTERN.fullmatch(self.digest):
            raise ValueError("invalid callback ingress acknowledgement digest")
        if type(self.commit_state) is not str or self.commit_state != "COMMITTED":
            raise ValueError("callback ingress acknowledgement is not committed")
        _validate_exact_int("ack high-watermark", self.high_watermark, minimum=1)
        if self.high_watermark != self.sequence:
            raise ValueError("callback ingress acknowledgement high-watermark mismatch")

    def validate_for(self, record: CtpTraderCallbackIngressRecordV2) -> None:
        if type(record) is not CtpTraderCallbackIngressRecordV2:
            raise ValueError("callback ingress acknowledgement requires exact record type")
        if not record.capture_complete:
            raise ValueError("incomplete callback record cannot be acknowledged")
        if (
            self.owner_id != record.owner_intent_id
            or self.sequence != record.source_sequence
            or self.digest != record.canonical_sha256
            or self.commit_state != "COMMITTED"
            or self.high_watermark != record.source_sequence
        ):
            raise ValueError("callback ingress acknowledgement does not match record")

    @property
    def owner_intent_id(self) -> str:
        return self.owner_id

    @property
    def source_sequence(self) -> int:
        return self.sequence

    @property
    def record_sha256(self) -> str:
        return self.digest


# Exact generated CThostFtdcTraderSpi inventory from ctp_trader_api.py.
# The source-AST test requires exact equality, so new vendor methods block the
# wrapper until their policy is reviewed and explicitly added here.
EXPECTED_TRADER_SPI_CALLBACK_NAMES = tuple(
    """
    OnFrontConnected OnFrontDisconnected OnHeartBeatWarning OnRspAuthenticate
    OnRspUserLogin OnRspUserLogout OnRspUserPasswordUpdate OnRspTradingAccountPasswordUpdate
    OnRspUserAuthMethod OnRspGenUserCaptcha OnRspGenUserText OnRspOrderInsert
    OnRspParkedOrderInsert OnRspParkedOrderAction OnRspOrderAction OnRspQryMaxOrderVolume
    OnRspSettlementInfoConfirm OnRspRemoveParkedOrder OnRspRemoveParkedOrderAction
    OnRspExecOrderInsert OnRspExecOrderAction OnRspForQuoteInsert OnRspQuoteInsert
    OnRspQuoteAction OnRspBatchOrderAction OnRspOptionSelfCloseInsert OnRspOptionSelfCloseAction
    OnRspCombActionInsert OnRspQryOrder OnRspQryTrade OnRspQryInvestorPosition
    OnRspQryTradingAccount OnRspQryInvestor OnRspQryTradingCode OnRspQryInstrumentMarginRate
    OnRspQryInstrumentCommissionRate OnRspQryExchange OnRspQryProduct OnRspQryInstrument
    OnRspQryDepthMarketData OnRspQryTraderOffer OnRspQrySettlementInfo OnRspQryTransferBank
    OnRspQryInvestorPositionDetail OnRspQryNotice OnRspQrySettlementInfoConfirm
    OnRspQryInvestorPositionCombineDetail OnRspQryCFMMCTradingAccountKey OnRspQryEWarrantOffset
    OnRspQryInvestorProductGroupMargin OnRspQryExchangeMarginRate OnRspQryExchangeMarginRateAdjust
    OnRspQryExchangeRate OnRspQrySecAgentACIDMap OnRspQryProductExchRate OnRspQryProductGroup
    OnRspQryMMInstrumentCommissionRate OnRspQryMMOptionInstrCommRate
    OnRspQryInstrumentOrderCommRate OnRspQrySecAgentTradingAccount OnRspQrySecAgentCheckMode
    OnRspQrySecAgentTradeInfo OnRspQryOptionInstrTradeCost OnRspQryOptionInstrCommRate
    OnRspQryExecOrder OnRspQryForQuote OnRspQryQuote OnRspQryOptionSelfClose
    OnRspQryInvestUnit OnRspQryCombInstrumentGuard OnRspQryCombAction OnRspQryTransferSerial
    OnRspQryAccountregister OnRspError OnRtnOrder OnRtnTrade OnErrRtnOrderInsert
    OnErrRtnOrderAction OnRtnInstrumentStatus OnRtnBulletin OnRtnTradingNotice
    OnRtnErrorConditionalOrder OnRtnExecOrder OnErrRtnExecOrderInsert OnErrRtnExecOrderAction
    OnErrRtnForQuoteInsert OnRtnQuote OnErrRtnQuoteInsert OnErrRtnQuoteAction
    OnRtnForQuoteRsp OnRtnCFMMCTradingAccountToken OnErrRtnBatchOrderAction OnRtnOptionSelfClose
    OnErrRtnOptionSelfCloseInsert OnErrRtnOptionSelfCloseAction OnRtnCombAction
    OnErrRtnCombActionInsert OnRspQryContractBank OnRspQryParkedOrder OnRspQryParkedOrderAction
    OnRspQryTradingNotice OnRspQryBrokerTradingParams OnRspQryBrokerTradingAlgos
    OnRspQueryCFMMCTradingAccountToken OnRtnFromBankToFutureByBank OnRtnFromFutureToBankByBank
    OnRtnRepealFromBankToFutureByBank OnRtnRepealFromFutureToBankByBank
    OnRtnFromBankToFutureByFuture OnRtnFromFutureToBankByFuture
    OnRtnRepealFromBankToFutureByFutureManual OnRtnRepealFromFutureToBankByFutureManual
    OnRtnQueryBankBalanceByFuture OnErrRtnBankToFutureByFuture OnErrRtnFutureToBankByFuture
    OnErrRtnRepealBankToFutureByFutureManual OnErrRtnRepealFutureToBankByFutureManual
    OnErrRtnQueryBankBalanceByFuture OnRtnRepealFromBankToFutureByFuture
    OnRtnRepealFromFutureToBankByFuture OnRspFromBankToFutureByFuture
    OnRspFromFutureToBankByFuture OnRspQueryBankAccountMoneyByFuture OnRtnOpenAccountByBank
    OnRtnCancelAccountByBank OnRtnChangeAccountByBank OnRspQryClassifiedInstrument
    OnRspQryCombPromotionParam OnRspQryRiskSettleInvstPosition OnRspQryRiskSettleProductStatus
    OnRspQrySPBMFutureParameter OnRspQrySPBMOptionParameter OnRspQrySPBMIntraParameter
    OnRspQrySPBMInterParameter OnRspQrySPBMPortfDefinition OnRspQrySPBMInvestorPortfDef
    OnRspQryInvestorPortfMarginRatio OnRspQryInvestorProdSPBMDetail
    OnRspQryInvestorCommoditySPMMMargin OnRspQryInvestorCommodityGroupSPMMMargin
    OnRspQrySPMMInstParam OnRspQrySPMMProductParam OnRspQrySPBMAddOnInterParameter
    OnRspQryRCAMSCombProductInfo OnRspQryRCAMSInstrParameter OnRspQryRCAMSIntraParameter
    OnRspQryRCAMSInterParameter OnRspQryRCAMSShortOptAdjustParam
    OnRspQryRCAMSInvestorCombPosition OnRspQryInvestorProdRCAMSMargin
    OnRspQryRULEInstrParameter OnRspQryRULEIntraParameter OnRspQryRULEInterParameter
    OnRspQryInvestorProdRULEMargin OnRspQryInvestorPortfSetting
    """.split()
)

_PRE_LOGIN_NAMES = ("OnFrontConnected", "OnRspAuthenticate", "OnRspUserLogin")
_ROUTEABLE_NAMES = (
    "OnRtnOrder",
    "OnRtnTrade",
    "OnRspOrderInsert",
    "OnErrRtnOrderInsert",
    "OnRspOrderAction",
    "OnErrRtnOrderAction",
)
_LIFECYCLE_POISON_NAMES = ("OnFrontDisconnected",)
_CONDITIONAL_QUERY_ERROR_NAMES = ("OnRspError",)
_AUDIT_INFORMATIONAL_NAMES = (
    "OnHeartBeatWarning",
    "OnRtnInstrumentStatus",
    "OnRtnBulletin",
    "OnRtnTradingNotice",
)
_AUDIT_QUERY_NAMES = tuple(
    name for name in EXPECTED_TRADER_SPI_CALLBACK_NAMES if name.startswith("OnRspQry")
)
_EXPLICIT_QUERY_AUDIT_NAMES = ("OnRspQryMaxOrderVolume",)

_UNSUPPORTED_FINANCIAL_NAMES = tuple(
    name
    for name in EXPECTED_TRADER_SPI_CALLBACK_NAMES
    if name
    not in set(
        _PRE_LOGIN_NAMES
        + _ROUTEABLE_NAMES
        + _LIFECYCLE_POISON_NAMES
        + _CONDITIONAL_QUERY_ERROR_NAMES
        + _AUDIT_INFORMATIONAL_NAMES
        + _AUDIT_QUERY_NAMES
        + _EXPLICIT_QUERY_AUDIT_NAMES
    )
)

_SAFE_RSP_INFO_FIELDS = ("ErrorID",)
_SAFE_ORDER_FIELDS = (
    "BrokerID",
    "InvestorID",
    "UserID",
    "InstrumentID",
    "ExchangeID",
    "OrderRef",
    "OrderSysID",
    "RequestID",
    "FrontID",
    "SessionID",
    "TradingDay",
    "SequenceNo",
    "NotifySequence",
    "Direction",
    "CombOffsetFlag",
    "CombHedgeFlag",
    "OrderStatus",
    "OrderSubmitStatus",
    "VolumeTotalOriginal",
    "VolumeTotal",
    "VolumeTraded",
    "LimitPrice",
)
_SAFE_INPUT_ORDER_FIELDS = (
    "BrokerID",
    "InvestorID",
    "UserID",
    "InstrumentID",
    "ExchangeID",
    "OrderRef",
    "RequestID",
)
# Every non-reserved CThostFtdcTradeField property is listed explicitly.
# SWIG reserve slots are omitted; account identity fields support exact local
# order/trade correlation and remain subject to the standard string bounds.
SAFE_TRADE_FIELD_NAMES = (
    "BrokerID",
    "InvestorID",
    "UserID",
    "OrderRef",
    "ExchangeID",
    "TradeID",
    "Direction",
    "OrderSysID",
    "ParticipantID",
    "ClientID",
    "TradingRole",
    "OffsetFlag",
    "HedgeFlag",
    "Price",
    "Volume",
    "TradeDate",
    "TradeTime",
    "TradeType",
    "PriceSource",
    "TraderID",
    "OrderLocalID",
    "ClearingPartID",
    "BusinessUnit",
    "SequenceNo",
    "TradingDay",
    "SettlementID",
    "BrokerOrderSeq",
    "TradeSource",
    "InvestUnitID",
    "InstrumentID",
    "ExchangeInstID",
)
_SAFE_POSITION_FIELDS = (
    "InstrumentID",
    "ExchangeID",
    "TradingDay",
    "PositionDate",
    "YdPosition",
    "Position",
    "TodayPosition",
    "PosiDirection",
    "HedgeFlag",
)
_SAFE_INSTRUMENT_FIELDS = (
    "InstrumentID",
    "ExchangeID",
    "ExchangeInstID",
    "ProductID",
    "ProductClass",
    "DeliveryYear",
    "DeliveryMonth",
    "VolumeMultiple",
    "PriceTick",
    "CreateDate",
    "OpenDate",
    "ExpireDate",
    "StartDelivDate",
    "EndDelivDate",
    "IsTrading",
)
_SAFE_DEPTH_FIELDS = (
    "InstrumentID",
    "ExchangeID",
    "TradingDay",
    "ActionDay",
    "UpdateTime",
    "UpdateMillisec",
    "LastPrice",
    "Volume",
    "Turnover",
    "OpenInterest",
    "BidPrice1",
    "BidVolume1",
    "AskPrice1",
    "AskVolume1",
)
_SAFE_INSTRUMENT_STATUS_FIELDS = (
    "ExchangeID",
    "ExchangeInstID",
    "InstrumentID",
    "InstrumentStatus",
)

# Exact return types in ctp_wrap.cpp getter wrappers for the safe fields below.
# SWIG_FromCharPtr produces str (or None for a null pointer), SWIG_From_char
# produces a one-character str, SWIG_From_int produces int, and
# SWIG_From_double produces float. In particular, bool is never accepted for
# an int or float even though Python subclasses bool from int.
SAFE_FIELD_KINDS: Mapping[str, str] = MappingProxyType(
    {
        **{
            name: "string"
            for name in (
                "ActionDay",
                "BrokerID",
                "BusinessUnit",
                "ClearingPartID",
                "ClientID",
                "CombHedgeFlag",
                "CombOffsetFlag",
                "CreateDate",
                "EndDelivDate",
                "ExchangeID",
                "ExchangeInstID",
                "ExpireDate",
                "InstrumentID",
                "InvestUnitID",
                "InvestorID",
                "MaxOrderRef",
                "OpenDate",
                "OrderLocalID",
                "OrderRef",
                "OrderSysID",
                "ParticipantID",
                "ProductID",
                "StartDelivDate",
                "TradeDate",
                "TradeID",
                "TradeTime",
                "TraderID",
                "TradingDay",
                "UpdateTime",
                "UserID",
            )
        },
        **{
            name: "char"
            for name in (
                "ActionFlag",
                "Direction",
                "HedgeFlag",
                "InstrumentStatus",
                "OffsetFlag",
                "OrderStatus",
                "OrderSubmitStatus",
                "PositionDate",
                "PosiDirection",
                "PriceSource",
                "ProductClass",
                "TradeSource",
                "TradeType",
                "TradingRole",
            )
        },
        **{
            name: "integer"
            for name in (
                "AskVolume1",
                "BidVolume1",
                "BrokerOrderSeq",
                "DeliveryMonth",
                "DeliveryYear",
                "ErrorID",
                "FrontID",
                "IsTrading",
                "NotifySequence",
                "OrderActionRef",
                "Position",
                "RequestID",
                "SequenceNo",
                "SessionID",
                "SettlementID",
                "TodayPosition",
                "UpdateMillisec",
                "Volume",
                "VolumeMultiple",
                "VolumeTotal",
                "VolumeTotalOriginal",
                "VolumeTraded",
                "YdPosition",
            )
        },
        **{
            name: "float"
            for name in (
                "AskPrice1",
                "BidPrice1",
                "LastPrice",
                "LimitPrice",
                "OpenInterest",
                "Price",
                "PriceTick",
                "Turnover",
            )
        },
    }
)


_ARGUMENT_NAME_OVERRIDES = {
    "OnRspAuthenticate": "pRspAuthenticateField",
    "OnRspUserLogin": "pRspUserLogin",
    "OnRspUserAuthMethod": "pRspUserAuthMethod",
    "OnRspGenUserCaptcha": "pRspGenUserCaptcha",
    "OnRspGenUserText": "pRspGenUserText",
    "OnRspOrderInsert": "pInputOrder",
    "OnRspOrderAction": "pInputOrderAction",
    "OnRspExecOrderInsert": "pInputExecOrder",
    "OnRspExecOrderAction": "pInputExecOrderAction",
    "OnRspForQuoteInsert": "pInputForQuote",
    "OnRspQuoteInsert": "pInputQuote",
    "OnRspQuoteAction": "pInputQuoteAction",
    "OnRspBatchOrderAction": "pInputBatchOrderAction",
    "OnRspOptionSelfCloseInsert": "pInputOptionSelfClose",
    "OnRspOptionSelfCloseAction": "pInputOptionSelfCloseAction",
    "OnRspCombActionInsert": "pInputCombAction",
    "OnRspParkedOrderInsert": "pParkedOrder",
    "OnRspQryMaxOrderVolume": "pQryMaxOrderVolume",
    "OnRspQrySecAgentTradingAccount": "pTradingAccount",
    "OnRspQryClassifiedInstrument": "pInstrument",
    "OnRtnTradingNotice": "pTradingNoticeInfo",
    "OnRtnOpenAccountByBank": "pOpenAccount",
    "OnRtnCancelAccountByBank": "pCancelAccount",
    "OnRtnChangeAccountByBank": "pChangeAccount",
    "OnRspFromBankToFutureByFuture": "pReqTransfer",
    "OnRspFromFutureToBankByFuture": "pReqTransfer",
    "OnRspQueryBankAccountMoneyByFuture": "pReqQueryAccount",
    "OnErrRtnOrderInsert": "pInputOrder",
    "OnErrRtnExecOrderInsert": "pInputExecOrder",
    "OnErrRtnForQuoteInsert": "pInputForQuote",
    "OnErrRtnQuoteInsert": "pInputQuote",
    "OnErrRtnOptionSelfCloseInsert": "pInputOptionSelfClose",
    "OnErrRtnCombActionInsert": "pInputCombAction",
    "OnErrRtnBankToFutureByFuture": "pReqTransfer",
    "OnErrRtnFutureToBankByFuture": "pReqTransfer",
    "OnErrRtnRepealBankToFutureByFutureManual": "pReqRepeal",
    "OnErrRtnRepealFutureToBankByFutureManual": "pReqRepeal",
    "OnErrRtnQueryBankBalanceByFuture": "pReqQueryAccount",
    "OnRtnFromBankToFutureByBank": "pRspTransfer",
    "OnRtnFromFutureToBankByBank": "pRspTransfer",
    "OnRtnRepealFromBankToFutureByBank": "pRspRepeal",
    "OnRtnRepealFromFutureToBankByBank": "pRspRepeal",
    "OnRtnFromBankToFutureByFuture": "pRspTransfer",
    "OnRtnFromFutureToBankByFuture": "pRspTransfer",
    "OnRtnRepealFromBankToFutureByFutureManual": "pRspRepeal",
    "OnRtnRepealFromFutureToBankByFutureManual": "pRspRepeal",
    "OnRtnQueryBankBalanceByFuture": "pNotifyQueryAccount",
    "OnRtnRepealFromBankToFutureByFuture": "pRspRepeal",
    "OnRtnRepealFromFutureToBankByFuture": "pRspRepeal",
}


def _argument_names_for(name: str) -> tuple[str, ...]:
    if name == "OnFrontConnected":
        return ()
    if name in ("OnFrontDisconnected", "OnHeartBeatWarning"):
        return ("nReason" if name == "OnFrontDisconnected" else "nTimeLapse",)
    if name == "OnRspError":
        return ("pRspInfo", "nRequestID", "bIsLast")
    if name.startswith("OnRsp"):
        if name in _ARGUMENT_NAME_OVERRIDES:
            first = _ARGUMENT_NAME_OVERRIDES[name]
        elif name.startswith("OnRspQry"):
            first = "p" + name[len("OnRspQry") :]
        else:
            first = "p" + name[len("OnRsp") :]
        return (first, "pRspInfo", "nRequestID", "bIsLast")
    if name.startswith("OnErrRtn"):
        first = _ARGUMENT_NAME_OVERRIDES.get(name, "p" + name[len("OnErrRtn") :])
        return (first, "pRspInfo")
    if name.startswith("OnRtn"):
        first = _ARGUMENT_NAME_OVERRIDES.get(name, "p" + name[len("OnRtn") :])
        return (first,)
    raise RuntimeError(f"callback inventory lacks argument-name policy: {name}")


CALLBACK_ARGUMENT_NAMES = {
    name: _argument_names_for(name) for name in EXPECTED_TRADER_SPI_CALLBACK_NAMES
}


def _safe_fields_for(name: str) -> tuple[tuple[int, tuple[str, ...]], ...]:
    mapping: dict[int, tuple[str, ...]] = {}
    if name == "OnRspAuthenticate":
        mapping = {0: ("BrokerID", "UserID"), 1: _SAFE_RSP_INFO_FIELDS}
    elif name == "OnRspUserLogin":
        mapping = {
            0: ("BrokerID", "UserID", "TradingDay", "FrontID", "SessionID", "MaxOrderRef"),
            1: _SAFE_RSP_INFO_FIELDS,
        }
    elif name == "OnRtnOrder" or name == "OnRspQryOrder":
        mapping = {0: _SAFE_ORDER_FIELDS}
        if name.startswith("OnRsp"):
            mapping[1] = _SAFE_RSP_INFO_FIELDS
    elif name in ("OnRspOrderInsert", "OnErrRtnOrderInsert"):
        mapping = {0: _SAFE_INPUT_ORDER_FIELDS, 1: _SAFE_RSP_INFO_FIELDS}
    elif name == "OnRspOrderAction" or name == "OnErrRtnOrderAction":
        mapping = {
            0: (
                "BrokerID",
                "InvestorID",
                "UserID",
                "InstrumentID",
                "ExchangeID",
                "OrderRef",
                "OrderSysID",
                "RequestID",
                "OrderActionRef",
                "FrontID",
                "SessionID",
                "ActionFlag",
            ),
            1: _SAFE_RSP_INFO_FIELDS,
        }
    elif name == "OnRtnTrade" or name == "OnRspQryTrade":
        mapping = {0: SAFE_TRADE_FIELD_NAMES}
        if name.startswith("OnRsp"):
            mapping[1] = _SAFE_RSP_INFO_FIELDS
    elif name == "OnRspQryInvestorPosition":
        mapping = {0: _SAFE_POSITION_FIELDS, 1: _SAFE_RSP_INFO_FIELDS}
    elif name in ("OnRspQryInstrument", "OnRspQryClassifiedInstrument"):
        mapping = {0: _SAFE_INSTRUMENT_FIELDS, 1: _SAFE_RSP_INFO_FIELDS}
    elif name == "OnRspQryDepthMarketData":
        mapping = {0: _SAFE_DEPTH_FIELDS, 1: _SAFE_RSP_INFO_FIELDS}
    elif name == "OnRspError":
        mapping = {0: _SAFE_RSP_INFO_FIELDS}
    elif name == "OnRtnInstrumentStatus":
        mapping = {0: _SAFE_INSTRUMENT_STATUS_FIELDS}
    elif name.startswith("OnRsp") and name != "OnRspError":
        # Query, lifecycle, and unsupported response callbacks retain only a
        # numeric provider error code. ErrorMsg is intentionally never copied.
        response_info_slot = 1 if name != "OnRspError" else 0
        mapping = {response_info_slot: _SAFE_RSP_INFO_FIELDS}
    elif name.startswith("OnErrRtn"):
        mapping = {1: _SAFE_RSP_INFO_FIELDS}
    return tuple(sorted(mapping.items()))


def _required_fields_for(name: str) -> tuple[tuple[int, str], ...]:
    if name == "OnRspError":
        return ((0, "ErrorID"),)
    if name == "OnRspAuthenticate":
        return ((1, "ErrorID"),)
    if name == "OnRspUserLogin":
        return tuple(
            (0, field) for field in ("BrokerID", "UserID", "TradingDay", "FrontID", "SessionID")
        ) + ((1, "ErrorID"),)
    if name == "OnRtnOrder":
        return tuple(
            (0, field)
            for field in (
                "BrokerID",
                "InvestorID",
                "UserID",
                "InstrumentID",
                "ExchangeID",
                "OrderRef",
                "RequestID",
                "TradingDay",
            )
        )
    if name in ("OnRspOrderAction", "OnErrRtnOrderAction"):
        required = tuple(
            (0, field)
            for field in (
                "InstrumentID",
                "ExchangeID",
                "BrokerID",
                "InvestorID",
                "UserID",
                "OrderRef",
                "RequestID",
                "OrderActionRef",
                "FrontID",
                "SessionID",
            )
        )
        if name == "OnRspOrderAction":
            return required + ((1, "ErrorID"),)
        return required + ((1, "ErrorID"),)
    if name == "OnRspOrderInsert":
        return tuple(
            (0, field)
            for field in (
                "BrokerID",
                "InvestorID",
                "UserID",
                "InstrumentID",
                "ExchangeID",
                "OrderRef",
                "RequestID",
            )
        ) + ((1, "ErrorID"),)
    if name == "OnErrRtnOrderInsert":
        return tuple(
            (0, field)
            for field in (
                "BrokerID",
                "InvestorID",
                "UserID",
                "InstrumentID",
                "ExchangeID",
                "OrderRef",
                "RequestID",
            )
        ) + ((1, "ErrorID"),)
    if name == "OnRtnTrade":
        return tuple(
            (0, field)
            for field in (
                "InstrumentID",
                "ExchangeID",
                "BrokerID",
                "InvestorID",
                "UserID",
                "TradeID",
                "OrderRef",
                "TradeDate",
                "TradingDay",
                "SequenceNo",
                "Price",
                "Volume",
            )
        )
    return ()


def _scalar_argument_slots(name: str) -> tuple[int, ...]:
    if name == "OnFrontConnected":
        return ()
    if name == "OnFrontDisconnected" or name == "OnHeartBeatWarning":
        return (0,)
    if name == "OnRspError":
        return (1, 2)
    if name.startswith("OnRsp"):
        return (2, 3)
    return ()


def _spec_for(name: str) -> CtpTraderCallbackSpecV2:
    if name in _PRE_LOGIN_NAMES:
        callback_class = CtpTraderCallbackClass.PRE_LOGIN
    elif name in _ROUTEABLE_NAMES:
        callback_class = CtpTraderCallbackClass.ROUTEABLE
    elif name in _LIFECYCLE_POISON_NAMES:
        callback_class = CtpTraderCallbackClass.LIFECYCLE_POISON
    elif name in _CONDITIONAL_QUERY_ERROR_NAMES:
        callback_class = CtpTraderCallbackClass.AUDIT_QUERY
    elif name in _AUDIT_INFORMATIONAL_NAMES:
        callback_class = CtpTraderCallbackClass.AUDIT_INFORMATIONAL
    elif name in _AUDIT_QUERY_NAMES or name in _EXPLICIT_QUERY_AUDIT_NAMES:
        callback_class = CtpTraderCallbackClass.AUDIT_QUERY
    elif name in _UNSUPPORTED_FINANCIAL_NAMES:
        callback_class = CtpTraderCallbackClass.UNSUPPORTED_FINANCIAL
    else:
        raise RuntimeError(f"callback inventory has no explicit class: {name}")
    safe_fields = _safe_fields_for(name)
    argument_names = CALLBACK_ARGUMENT_NAMES[name]
    return CtpTraderCallbackSpecV2(
        callback_class=callback_class,
        argument_names=argument_names,
        expected_argument_count=len(argument_names),
        scalar_argument_slots=_scalar_argument_slots(name),
        safe_fields_by_slot=safe_fields,
        required_fields=_required_fields_for(name),
        active_phase_poison=name in _PRE_LOGIN_NAMES or name in _LIFECYCLE_POISON_NAMES,
        requires_active_query_match=name == "OnRspError",
    )


def build_callback_ingress_record_v2(
    *,
    owner_intent_id: str,
    callback_name: str,
    source_phase: CtpTraderCallbackPhase,
    source_tags: CtpTraderCallbackSourceTagsV2,
    connection_generation: int,
    source_sequence: int,
    callback_monotonic_ns: int,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any] | None = None,
) -> CtpTraderCallbackIngressRecordV2:
    """Create a bounded source record from a callback's positional arguments.

    Only spec-listed scalar slots and field getters are copied. Unexpected
    keyword arguments, getter errors, missing required fields, unsafe types,
    argument-count mismatches, and size/count overflow produce an incomplete
    record. The caller must poison its ingress and must not publish such a
    record to the durable sink.
    """

    _validate_id("owner intent id", owner_intent_id)
    if type(callback_name) is not str or callback_name not in CALLBACK_SPECS:
        raise ValueError("unknown Trader SPI callback")
    if type(source_phase) is not CtpTraderCallbackPhase:
        raise ValueError("invalid source phase")
    if type(source_tags) is not CtpTraderCallbackSourceTagsV2:
        raise ValueError("source tags must be exact immutable V2 tags")
    _validate_exact_int("connection generation", connection_generation, minimum=0)
    _validate_exact_int("source sequence", source_sequence, minimum=1)
    _validate_exact_int("callback monotonic timestamp", callback_monotonic_ns, minimum=1)
    if type(args) is not tuple:
        raise ValueError("callback positional arguments must be an exact tuple")
    kwargs_unsupported = False
    if kwargs is None:
        kwargs = {}
    elif type(kwargs) is not dict:
        # Never iterate or truth-test a caller-defined mapping: it can expose
        # secret values or run arbitrary code during capture.
        kwargs_unsupported = True
        kwargs = {}
    elif kwargs:
        kwargs_unsupported = True

    spec = CALLBACK_SPECS[callback_name]
    missing: list[str] = []
    if kwargs_unsupported:
        # Do not inspect names or values: a caller could place secrets in a
        # keyword argument. Native CTP invokes these callbacks positionally.
        missing.append("kwargs_unsupported")
    if len(args) != spec.expected_argument_count:
        missing.append("callback_argument_count_mismatch")
    if len(args) > _MAX_CALLBACK_ARGUMENTS:
        missing.append("callback_argument_limit_exceeded")

    callback_arguments: list[CtpTraderCallbackArgumentV2] = []
    max_slots = min(spec.expected_argument_count, _MAX_CALLBACK_ARGUMENTS)
    for slot in range(max_slots):
        present = slot < len(args)
        if not present:
            callback_arguments.append(
                CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], False, False, None)
            )
            missing.append(f"arg:{slot}:missing")
            continue
        value = args[slot]
        if slot not in spec.scalar_argument_slots:
            # Native pointer arguments are never retained. Null pointers remain
            # distinguishable from absent positional arguments.
            if value is None:
                callback_arguments.append(
                    CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], True, False, None)
                )
            elif _is_scalar(value):
                callback_arguments.append(
                    CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], True, False, None)
                )
                missing.append(f"arg:{slot}:unexpected_scalar")
            else:
                callback_arguments.append(
                    CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], True, False, None)
                )
            continue
        if not _is_allowed_scalar_argument(callback_name, slot, value):
            callback_arguments.append(
                CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], True, False, None)
            )
            missing.append(f"arg:{slot}:invalid_scalar")
            continue
        callback_arguments.append(
            CtpTraderCallbackArgumentV2(slot, spec.argument_names[slot], True, True, value)
        )

    field_entries: list[CallbackFieldEntryV2] = []
    required = set(spec.required_fields)
    for argument_slot, field_names in spec.safe_fields_by_slot:
        field_obj = args[argument_slot] if argument_slot < len(args) else None
        for field_name in field_names:
            if len(field_entries) >= _MAX_FLATTENED_FIELDS:
                missing.append("flattened_field_limit_exceeded")
                break
            if field_obj is None:
                state = CtpTraderCallbackFieldValueV2(False, None, False)
                field_entries.append((argument_slot, field_name, state))
                if (argument_slot, field_name) in required:
                    missing.append(f"arg:{argument_slot}.{field_name}:missing")
                continue
            try:
                declared_field = inspect.getattr_static(field_obj, field_name, _MISSING_ATTRIBUTE)
            except Exception:
                state = CtpTraderCallbackFieldValueV2(True, None, False)
                field_entries.append((argument_slot, field_name, state))
                missing.append(f"arg:{argument_slot}.{field_name}:getter_error")
                continue
            if declared_field is _MISSING_ATTRIBUTE:
                state = CtpTraderCallbackFieldValueV2(False, None, False)
                field_entries.append((argument_slot, field_name, state))
                if (argument_slot, field_name) in required:
                    missing.append(f"arg:{argument_slot}.{field_name}:missing")
                continue
            try:
                field_value = getattr(field_obj, field_name)
            except Exception:
                state = CtpTraderCallbackFieldValueV2(True, None, False)
                field_entries.append((argument_slot, field_name, state))
                missing.append(f"arg:{argument_slot}.{field_name}:getter_error")
                continue
            if type(field_value) is str and _string_exceeds_limit(field_value):
                state = CtpTraderCallbackFieldValueV2(True, None, False)
                field_entries.append((argument_slot, field_name, state))
                missing.append(f"arg:{argument_slot}.{field_name}:string_too_large")
                continue
            if (
                SAFE_FIELD_KINDS[field_name] == "float"
                and type(field_value) is float
                and not math.isfinite(field_value)
            ):
                state = CtpTraderCallbackFieldValueV2(True, None, False)
                field_entries.append((argument_slot, field_name, state))
                missing.append(f"arg:{argument_slot}.{field_name}:non_finite")
                continue
            if not _matches_safe_field_type(field_name, field_value):
                state = CtpTraderCallbackFieldValueV2(True, None, False)
                field_entries.append((argument_slot, field_name, state))
                missing.append(f"arg:{argument_slot}.{field_name}:unsafe_type")
                continue
            field_entries.append(
                (argument_slot, field_name, CtpTraderCallbackFieldValueV2(True, field_value, True))
            )
            if (argument_slot, field_name) in required and field_value is None:
                missing.append(f"arg:{argument_slot}.{field_name}:null_required")

    missing = list(dict.fromkeys(missing))
    if len(missing) > _MAX_MISSING_FIELDS:
        missing = missing[:_MAX_MISSING_FIELDS]
        missing[-1] = "missing_field_limit_exceeded"
    capture_complete = not missing
    values: dict[str, Any] = {
        "owner_intent_id": owner_intent_id,
        "callback_name": callback_name,
        "callback_class": CALLBACK_SPECS[callback_name].callback_class,
        "source_phase": source_phase,
        "source_instance_id": source_tags.source_instance_id,
        "native_client_epoch": source_tags.native_client_epoch,
        "native_api_source_id": source_tags.native_api_source_id,
        "native_spi_source_id": source_tags.native_spi_source_id,
        "native_api_generation": source_tags.native_api_generation,
        "source_connection_generation": source_tags.connection_generation,
        "connection_generation": connection_generation,
        "source_sequence": source_sequence,
        "callback_monotonic_ns": callback_monotonic_ns,
        "callback_arguments": tuple(callback_arguments),
        "flattened_fields": tuple(field_entries),
        "capture_complete": capture_complete,
        "missing_field_names": tuple(missing),
    }
    payload = _payload_for_values(values)
    digest = _digest_payload(payload)
    if len(_canonical_bytes(payload)) + 80 > _MAX_RECORD_BYTES:
        return _build_oversize_record(values)
    record = CtpTraderCallbackIngressRecordV2(**values, canonical_sha256=digest)
    return record


def callback_ingress_disposition(
    record: CtpTraderCallbackIngressRecordV2,
    *,
    active_query_request_id: int | None = None,
    active_query_kind: str | None = None,
) -> CtpTraderCallbackDisposition:
    """Apply static callback/phase policy, leaving lifecycle transitions to owner."""

    if type(record) is not CtpTraderCallbackIngressRecordV2 or not record.capture_complete:
        return CtpTraderCallbackDisposition.POISON
    spec = CALLBACK_SPECS[record.callback_name]
    if record.source_phase is CtpTraderCallbackPhase.POISONED:
        return CtpTraderCallbackDisposition.POISON
    if record.callback_name in _LIFECYCLE_POISON_CALLBACK_NAMES:
        return CtpTraderCallbackDisposition.POISON
    if record.source_phase is CtpTraderCallbackPhase.PRE_LOGIN:
        if record.callback_name not in _PRE_LOGIN_CALLBACK_NAMES:
            return CtpTraderCallbackDisposition.POISON
        if record.callback_name != "OnFrontConnected":
            request_id = record.scalar_argument(2)
            terminal = record.scalar_argument(3)
            error_id = record.field_value(1, "ErrorID")
            if (
                type(request_id) is not int
                or request_id <= 0
                or not _is_last_flag_true(terminal)
                or error_id is None
                or not error_id.present
                or type(error_id.value) is not int
                or error_id.value != 0
            ):
                return CtpTraderCallbackDisposition.POISON
        return CtpTraderCallbackDisposition.PRE_LOGIN_CANDIDATE
    if record.source_phase is not CtpTraderCallbackPhase.ACTIVE:
        return CtpTraderCallbackDisposition.POISON
    if spec.active_phase_poison or record.callback_name in _UNSUPPORTED_CALLBACK_NAMES:
        return CtpTraderCallbackDisposition.POISON
    if record.callback_name in _ROUTEABLE_CALLBACK_NAMES:
        return CtpTraderCallbackDisposition.ROUTEABLE
    if spec.requires_active_query_match:
        request_id = record.scalar_argument(1)
        if (
            type(request_id) is not int
            or request_id <= 0
            or type(active_query_request_id) is not int
            or type(active_query_kind) is not str
            or active_query_kind not in AUDIT_QUERY_CALLBACK_NAMES
            or request_id != active_query_request_id
        ):
            return CtpTraderCallbackDisposition.POISON
        return CtpTraderCallbackDisposition.AUDIT_QUERY
    if spec.callback_class is CtpTraderCallbackClass.AUDIT_QUERY:
        request_id = record.scalar_argument(2)
        if (
            type(request_id) is not int
            or request_id <= 0
            or type(active_query_request_id) is not int
            or type(active_query_kind) is not str
            or active_query_kind != record.callback_name
            or request_id != active_query_request_id
        ):
            return CtpTraderCallbackDisposition.POISON
        return CtpTraderCallbackDisposition.AUDIT_QUERY
    if spec.callback_class is CtpTraderCallbackClass.AUDIT_INFORMATIONAL:
        return CtpTraderCallbackDisposition.AUDIT_INFORMATIONAL
    return CtpTraderCallbackDisposition.POISON


def validate_expected_prelogin_step(
    record: CtpTraderCallbackIngressRecordV2,
    *,
    expected_callback_name: str,
    expected_request_id: int | None = None,
    bound_broker_id: str | None = None,
    bound_user_id: str | None = None,
) -> bool:
    """Validate terminal, identity-bearing login facts for the owning client.

    This is a predicate, not a state machine. The client must separately prove
    the expected connect/auth/login ordering and exact SPI registration tags.
    """

    if (
        type(record) is not CtpTraderCallbackIngressRecordV2
        or not record.capture_complete
        or record.source_phase is not CtpTraderCallbackPhase.PRE_LOGIN
        or record.callback_name != expected_callback_name
        or expected_callback_name not in _PRE_LOGIN_CALLBACK_NAMES
    ):
        return False
    if expected_callback_name == "OnFrontConnected":
        return expected_request_id is None and record.source_sequence > 0
    if (
        type(bound_broker_id) is not str
        or not bound_broker_id
        or type(bound_user_id) is not str
        or not bound_user_id
    ):
        return False
    request_slot = 2
    request_id = record.scalar_argument(request_slot)
    last_slot = 3
    if (
        type(expected_request_id) is not int
        or expected_request_id <= 0
        or type(request_id) is not int
        or request_id != expected_request_id
        or not _is_last_flag_true(record.scalar_argument(last_slot))
    ):
        return False
    error_value = record.field_value(1, "ErrorID")
    if (
        error_value is None
        or not error_value.present
        or type(error_value.value) is not int
        or error_value.value != 0
    ):
        return False
    if expected_callback_name == "OnRspAuthenticate":
        for name, expected in (("BrokerID", bound_broker_id), ("UserID", bound_user_id)):
            field = record.field_value(0, name)
            if (
                field is None
                or not field.present
                or type(field.value) is not str
                or field.value != expected
            ):
                return False
        return True
    broker = record.field_value(0, "BrokerID")
    investor = record.field_value(0, "UserID")
    trading_day = record.field_value(0, "TradingDay")
    front_id = record.field_value(0, "FrontID")
    session_id = record.field_value(0, "SessionID")
    return bool(
        broker is not None
        and broker.present
        and type(broker.value) is str
        and bool(broker.value)
        and broker.value == bound_broker_id
        and investor is not None
        and investor.present
        and type(investor.value) is str
        and bool(investor.value)
        and investor.value == bound_user_id
        and trading_day is not None
        and trading_day.present
        and type(trading_day.value) is str
        and _is_ctp_trading_day(trading_day.value)
        and front_id is not None
        and front_id.present
        and type(front_id.value) is int
        and front_id.value > 0
        and session_id is not None
        and session_id.present
        and type(session_id.value) is int
        and session_id.value > 0
    )


_CALLBACK_DISPATCH_INSTALL_MARKER = "__ctp_callback_ingress_dispatch_install_v2__"
SKIP_ORIGINAL_CALLBACK = object()


def install_trader_spi_callback_dispatch(
    cls: type,
    dispatcher: Callable[[Any, str, tuple[Any, ...], Mapping[str, Any], Callable[..., Any]], Any],
) -> type:
    """Override all exact Trader SPI methods on ``cls`` with ingress wrappers.

    The dispatcher runs first with ``(instance, name, args, kwargs, original)``;
    ``original`` is the unbound method captured from the previous MRO. If the
    dispatcher returns :data:`SKIP_ORIGINAL_CALLBACK`, the old handler is
    suppressed (for a poison/failed transaction). Otherwise the wrapper calls
    the original exactly once. Dispatcher exceptions propagate without calling
    the original. Reinstalling the same dispatcher is idempotent; a different
    dispatcher on the same class is rejected to prevent wrapper stacking.
    """

    if not isinstance(cls, type) or not callable(dispatcher):
        raise TypeError("callback wrapper requires a class and callable dispatcher")
    installed = cls.__dict__.get(_CALLBACK_DISPATCH_INSTALL_MARKER)
    if installed is not None:
        previous_dispatcher, previous_names = installed
        if (
            previous_dispatcher is dispatcher
            and previous_names == EXPECTED_TRADER_SPI_CALLBACK_NAMES
        ):
            return cls
        raise RuntimeError("Trader SPI callback dispatcher already installed")

    resolved: dict[str, Callable[..., Any]] = {}
    discovered: set[str] = set()
    for base in cls.__mro__:
        if base is object:
            continue
        for name in vars(base):
            if name.startswith("On") and callable(getattr(cls, name, None)):
                discovered.add(name)
    unknown = discovered - set(CALLBACK_SPECS)
    missing = set(CALLBACK_SPECS) - discovered
    if unknown or missing:
        raise RuntimeError(
            "Trader SPI callback inventory mismatch: "
            f"unknown={','.join(sorted(unknown))}; missing={','.join(sorted(missing))}"
        )
    for name in EXPECTED_TRADER_SPI_CALLBACK_NAMES:
        original = getattr(cls, name)
        if getattr(original, "__ctp_callback_ingress_wrapper_v2__", False):
            raise RuntimeError("Trader SPI method is already wrapped outside installer")
        resolved[name] = original

    for name, original in resolved.items():

        @wraps(original)
        def wrapper(self, *args, __name=name, __original=original, **kwargs):
            decision = dispatcher(self, __name, args, kwargs, __original)
            if decision is SKIP_ORIGINAL_CALLBACK:
                return None
            return __original(self, *args, **kwargs)

        setattr(wrapper, "__ctp_callback_ingress_wrapper_v2__", True)
        setattr(wrapper, "__ctp_callback_ingress_name_v2__", name)
        setattr(cls, name, wrapper)
    setattr(
        cls, _CALLBACK_DISPATCH_INSTALL_MARKER, (dispatcher, EXPECTED_TRADER_SPI_CALLBACK_NAMES)
    )
    return cls


def _build_oversize_record(values: dict[str, Any]) -> CtpTraderCallbackIngressRecordV2:
    missing_values = list(
        dict.fromkeys((*values["missing_field_names"], "record_size_limit_exceeded"))
    )
    if len(missing_values) > _MAX_MISSING_FIELDS:
        missing_values = missing_values[: _MAX_MISSING_FIELDS - 1]
        missing_values.append("record_size_limit_exceeded")
    missing = tuple(missing_values)
    safe_arguments = tuple(
        item
        if item.scalar_captured
        else CtpTraderCallbackArgumentV2(item.slot, item.name, item.present, False, None)
        for item in values["callback_arguments"]
    )
    compact_values = dict(values)
    compact_values["callback_arguments"] = safe_arguments
    compact_values["flattened_fields"] = ()
    compact_values["capture_complete"] = False
    compact_values["missing_field_names"] = missing[:_MAX_MISSING_FIELDS]
    digest = _digest_payload(_payload_for_values(compact_values))
    compact = CtpTraderCallbackIngressRecordV2(**compact_values, canonical_sha256=digest)
    if len(compact.canonical_bytes()) > _MAX_RECORD_BYTES:
        # Identity metadata is strictly bounded, so this is only reachable if
        # the implementation's own limits are inconsistent.
        raise ValueError("callback record cannot fit bounded incomplete representation")
    return compact


def _payload_for_values(values: dict[str, Any]) -> dict[str, Any]:
    record = object.__new__(CtpTraderCallbackIngressRecordV2)
    for key, value in values.items():
        object.__setattr__(record, key, value)
    return CtpTraderCallbackIngressRecordV2._payload(record)


def _digest_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _is_scalar(value: Any) -> bool:
    if type(value) is str:
        try:
            value.encode("utf-8")
            return True
        except UnicodeEncodeError:
            return False
    if type(value) is int:
        return value.bit_length() <= 128
    return type(value) in (float, bool, type(None)) and not (
        type(value) is float and not math.isfinite(value)
    )


def _matches_safe_field_type(field_name: str, value: Any) -> bool:
    kind = SAFE_FIELD_KINDS.get(field_name)
    if kind == "string":
        return value is None or (type(value) is str and not _string_exceeds_limit(value))
    if kind == "char":
        return type(value) is str and len(value) == 1 and not _string_exceeds_limit(value)
    if kind == "integer":
        return type(value) is int and value.bit_length() <= 128
    if kind == "float":
        return type(value) is float and math.isfinite(value)
    return False


def _is_allowed_scalar_argument(callback_name: str, slot: int, value: Any) -> bool:
    if not _is_scalar(value):
        return False
    if type(value) is str:
        return False
    if type(value) is float:
        return False
    if value is None:
        return False
    if callback_name == "OnRspError":
        request_slot, terminal_flag_slot = 1, 2
    elif callback_name.startswith("OnRsp"):
        request_slot, terminal_flag_slot = 2, 3
    else:
        request_slot, terminal_flag_slot = -1, -1
    if slot == terminal_flag_slot:
        return type(value) is bool
    if slot == request_slot:
        return type(value) is int
    if callback_name in ("OnFrontDisconnected", "OnHeartBeatWarning"):
        return type(value) is int
    return type(value) is int


def _validate_scalar(value: Any, *, label: str) -> None:
    if not _is_scalar(value):
        raise ValueError(f"{label} must be an exact primitive scalar")
    if type(value) is str and _string_exceeds_limit(value):
        raise ValueError(f"{label} exceeds string size limit")


def _string_exceeds_limit(value: str) -> bool:
    if len(value) > _MAX_STRING_BYTES:
        return True
    try:
        return len(value.encode("utf-8")) > _MAX_STRING_BYTES
    except UnicodeEncodeError:
        return True


def _validate_id(label: str, value: Any) -> None:
    if type(value) is not str or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid {label}")
    if len(value.encode("ascii")) > _MAX_ID_BYTES:
        raise ValueError(f"{label} exceeds identifier size limit")


def _validate_exact_int(label: str, value: Any, *, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {label}")


def _validate_field_name(value: Any) -> None:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value, re.ASCII):
        raise ValueError("invalid callback field name")
    if _is_sensitive_field_name(value):
        raise ValueError("sensitive callback field is not allowed")


def _is_safe_missing_reason(value: str) -> bool:
    if value in {
        "kwargs_unsupported",
        "callback_argument_count_mismatch",
        "callback_argument_limit_exceeded",
        "flattened_field_limit_exceeded",
        "missing_field_limit_exceeded",
        "record_size_limit_exceeded",
    }:
        return True
    match = re.fullmatch(
        r"arg:[0-7](?:\.([A-Za-z][A-Za-z0-9_]{0,63}))?:(missing|null_required|unexpected_scalar|invalid_scalar|getter_error|unsafe_type|string_too_large|non_finite)",
        value,
        re.ASCII,
    )
    if match is None:
        return False
    field_name = match.group(1)
    if field_name is not None:
        try:
            _validate_field_name(field_name)
        except ValueError:
            return False
    return True


def _validate_argument_name(value: Any) -> None:
    # Generated pointer parameter names can contain words such as Password or
    # AuthMethod.  These labels carry no argument value; actual captured fields
    # continue to use the stricter sensitive-name filter above.
    if type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value, re.ASCII):
        raise ValueError("invalid callback argument name")


def _is_sensitive_field_name(value: str) -> bool:
    normalized = value.lower().replace("_", "")
    return any(
        token in normalized
        for token in (
            "password",
            "passwd",
            "authcode",
            "captcha",
            "token",
            "bankpassword",
            "bankpwd",
            "tradepassword",
            "accountpassword",
            "secret",
        )
    )


def _is_ctp_trading_day(value: str) -> bool:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") == value
    except ValueError:
        return False


def _is_last_flag_true(value: Any) -> bool:
    return value is True or (type(value) is int and value == 1)


if len(set(EXPECTED_TRADER_SPI_CALLBACK_NAMES)) != len(EXPECTED_TRADER_SPI_CALLBACK_NAMES):
    raise RuntimeError("duplicate callback name in frozen inventory")

CALLBACK_SPECS: Mapping[str, CtpTraderCallbackSpecV2] = {
    name: _spec_for(name) for name in EXPECTED_TRADER_SPI_CALLBACK_NAMES
}
CALLBACK_SPECS = MappingProxyType(dict(CALLBACK_SPECS))
AUDIT_QUERY_CALLBACK_NAMES = frozenset(
    name
    for name, spec in CALLBACK_SPECS.items()
    if spec.callback_class is CtpTraderCallbackClass.AUDIT_QUERY and name != "OnRspError"
)

_ROUTEABLE_CALLBACK_NAMES = frozenset(_ROUTEABLE_NAMES)
_PRE_LOGIN_CALLBACK_NAMES = frozenset(_PRE_LOGIN_NAMES)
_LIFECYCLE_POISON_CALLBACK_NAMES = frozenset(_LIFECYCLE_POISON_NAMES)
_UNSUPPORTED_CALLBACK_NAMES = frozenset(_UNSUPPORTED_FINANCIAL_NAMES)

_ALLOWLISTED_FIELD_NAMES = {
    field_name
    for spec in CALLBACK_SPECS.values()
    for _slot, field_names in spec.safe_fields_by_slot
    for field_name in field_names
}
if _ALLOWLISTED_FIELD_NAMES != set(SAFE_FIELD_KINDS):
    missing_kinds = sorted(_ALLOWLISTED_FIELD_NAMES - set(SAFE_FIELD_KINDS))
    unused_kinds = sorted(set(SAFE_FIELD_KINDS) - _ALLOWLISTED_FIELD_NAMES)
    raise RuntimeError(
        "safe callback field type inventory mismatch: "
        f"missing={','.join(missing_kinds)}; unused={','.join(unused_kinds)}"
    )

for _name, _spec in CALLBACK_SPECS.items():
    if sum(len(names) for _slot, names in _spec.safe_fields_by_slot) > _MAX_FLATTENED_FIELDS:
        raise RuntimeError(f"callback field limit exceeded in {_name}")
    if any(
        _is_sensitive_field_name(field_name)
        for _slot, field_names in _spec.safe_fields_by_slot
        for field_name in field_names
    ):
        raise RuntimeError(f"sensitive field entered callback allowlist in {_name}")


__all__ = [
    "AUDIT_QUERY_CALLBACK_NAMES",
    "CALLBACK_SPECS",
    "EXPECTED_TRADER_SPI_CALLBACK_NAMES",
    "SAFE_FIELD_KINDS",
    "SAFE_TRADE_FIELD_NAMES",
    "SKIP_ORIGINAL_CALLBACK",
    "CallbackFieldEntryV2",
    "CallbackScalar",
    "CtpTraderCallbackArgumentV2",
    "CtpTraderCallbackClass",
    "CtpTraderCallbackDisposition",
    "CtpTraderCallbackFieldValueV2",
    "CtpTraderCallbackIngressAckV2",
    "CtpTraderCallbackIngressRecordV2",
    "CtpTraderCallbackPhase",
    "CtpTraderCallbackSourceTagsV2",
    "CtpTraderCallbackSpecV2",
    "build_callback_ingress_record_v2",
    "callback_ingress_disposition",
    "install_trader_spi_callback_dispatch",
    "validate_expected_prelogin_step",
]
