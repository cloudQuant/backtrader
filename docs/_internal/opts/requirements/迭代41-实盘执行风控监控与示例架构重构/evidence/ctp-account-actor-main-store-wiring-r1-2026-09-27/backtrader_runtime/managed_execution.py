"""Configuration-bound Backtrader projection for a composed managed runtime.

This module does not import an SDK, execution package, provider, or broker at
module import time.  The caller must first validate ``runtime/config.yaml``
and compose a sealed managed capability runtime.  Only then may it bind the
bridge to a :class:`backtrader.stores.BtApiStore` before startup.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import math
import re
import struct
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from types import MappingProxyType, SimpleNamespace
from typing import Any, Optional

from .framework_projection import (
    FrameworkProjectionClaim,
    FrameworkProjectionJournal,
    FrameworkProjectionRecoveryError,
    FrameworkSourceEventClaim,
    canonical_framework_projection_fingerprint,
)
from .registry import EffectiveRuntimeConfig


class ManagedExecutionBindingError(RuntimeError):
    """The Backtrader projection cannot safely map or dispatch an order."""


class CtpQueueReceiptState(str, Enum):
    """Local classification of an asynchronous CTP Store queue receipt.

    These values deliberately are not provider execution states. In particular,
    ``UNKNOWN`` means only that the SDK queue accepted the command; it does not
    mean the CTP front or exchange accepted an order or cancellation.
    """

    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class CtpQueueReceiptClassification:
    """Validated local queue result, with no provider-observation fields."""

    operation: str
    state: CtpQueueReceiptState
    receipt_id: str
    error_code: Optional[str] = None
    queued: bool = False


_CTP_QUEUE_RECEIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CTP_QUEUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CTP_QUEUE_ERROR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CTP_QUEUE_RECEIPT_FIELDS = frozenset(
    {
        "kind",
        "command",
        "receipt_id",
        "bt_order_ref",
        "client_order_id",
        "status",
        "queued",
        "priority",
        "queue_depth",
        "error_code",
        "error_msg",
    }
)


def _ctp_queue_expected_identity(value: Any, name: str) -> Any:
    """Validate one Store correlation identity before comparing its echo."""

    if name == "bt_order_ref":
        # Recovered SDK bindings have no Backtrader reference. In that case
        # the Store receipt must still echo the durable native CTP OrderRef
        # below; None is an explicit missing framework identity, not a
        # wildcard.
        if value is None:
            return None
        if type(value) is int and value > 0:
            return value
        if (
            type(value) is str
            and value
            and value == value.strip()
            and value.isascii()
            and _CTP_QUEUE_TOKEN_RE.fullmatch(value)
        ):
            return value
        raise ManagedExecutionBindingError("managed CTP expected bt_order_ref is invalid")
    if name == "client_order_id":
        # For CTP this is the durable native OrderRef, reserved by the SDK
        # with its fixed-width numeric representation.
        if type(value) is str and value.isascii() and value.isdigit() and len(value) == 12:
            return value
    raise ManagedExecutionBindingError("managed CTP expected client_order_id is invalid")


def classify_ctp_queue_receipt(
    response: Any,
    *,
    operation: str,
    expected_bt_order_ref: Any,
    expected_client_order_id: str,
) -> CtpQueueReceiptClassification:
    """Classify a Store queue receipt without inventing provider ACK evidence.

    The expected identities come from the already validated typed managed CTP
    dispatch and Store binding. A queued receipt becomes durable ``UNKNOWN``
    at the caller; a rejected receipt becomes local ``REJECTED`` only after
    those identities and the Store-generated receipt envelope match exactly.
    This helper never constructs a ``ProviderObservation`` or
    ``CancelObservation``.
    """

    if type(operation) is not str or operation not in {"submit", "cancel"}:
        raise ManagedExecutionBindingError("managed CTP queue operation is invalid")
    expected_ref = _ctp_queue_expected_identity(expected_bt_order_ref, "bt_order_ref")
    expected_client_id = _ctp_queue_expected_identity(expected_client_order_id, "client_order_id")
    if not isinstance(response, Mapping):
        raise ManagedExecutionBindingError("managed CTP queue receipt is not a mapping")
    if not set(response).issubset(_CTP_QUEUE_RECEIPT_FIELDS):
        raise ManagedExecutionBindingError("managed CTP queue receipt contains unexpected fields")
    queued = response.get("queued")
    expected_fields = {
        "kind",
        "command",
        "receipt_id",
        "bt_order_ref",
        "client_order_id",
        "status",
        "queued",
        "priority",
        "queue_depth",
    }
    if queued is False:
        expected_fields.update(("error_code", "error_msg"))
    if type(queued) is not bool or set(response) != expected_fields:
        raise ManagedExecutionBindingError("managed CTP queue receipt fields are incomplete")

    if (
        response.get("kind") != "command_receipt"
        or response.get("command") != operation
        or type(response.get("receipt_id")) is not str
        or not _CTP_QUEUE_RECEIPT_ID_RE.fullmatch(response["receipt_id"])
        or response.get("bt_order_ref") != expected_ref
        or type(response.get("bt_order_ref")) is not type(expected_ref)
        or response.get("client_order_id") != expected_client_id
        or type(response.get("client_order_id")) is not str
    ):
        raise ManagedExecutionBindingError("managed CTP queue receipt identity is invalid")

    priority = response.get("priority")
    allowed_priorities = {"cancel"} if operation == "cancel" else {"open", "close"}
    queue_depth = response.get("queue_depth")
    if (
        type(priority) is not str
        or priority not in allowed_priorities
        or type(queue_depth) is not int
        or queue_depth < 0
    ):
        raise ManagedExecutionBindingError("managed CTP queue receipt evidence is invalid")

    receipt_id = response["receipt_id"]
    if queued is True:
        if response.get("status") != "submitted":
            raise ManagedExecutionBindingError("managed CTP queued receipt status is invalid")
        return CtpQueueReceiptClassification(
            operation=operation,
            state=CtpQueueReceiptState.UNKNOWN,
            receipt_id=receipt_id,
            queued=True,
        )

    error_code = response.get("error_code")
    if (
        response.get("status") != "rejected"
        or type(error_code) is not str
        or not _CTP_QUEUE_ERROR_RE.fullmatch(error_code)
        or type(response.get("error_msg")) is not str
        or not response["error_msg"].strip()
    ):
        raise ManagedExecutionBindingError("managed CTP rejected receipt status is invalid")
    return CtpQueueReceiptClassification(
        operation=operation,
        state=CtpQueueReceiptState.REJECTED,
        receipt_id=receipt_id,
        error_code=error_code,
        queued=False,
    )


class CtpManagedExecutionAdapterPlaceholder:
    """Typed fail-closed placeholder for the uncomposed CTP write route.

    The Store contract is ready to carry managed CTP identities, but the
    repository has no write-authorizing CTP admission yet. Its current CTP
    admission/configuration surfaces are private-read only, and the SDK Store
    dispatcher returns an asynchronous queue receipt rather than the provider
    observation required by the durable execution facade. This placeholder
    makes a CTP binding explicit while refusing before the SDK callback can
    enqueue anything.
    """

    ctp_managed_execution_version = 1

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    @staticmethod
    def _reject() -> None:
        error = ManagedExecutionBindingError(
            "MANAGED_CTP_WRITE_COMPOSITION_UNAVAILABLE: a write-authorizing CTP admission "
            "and synchronous BtApi execution-observation handoff are required"
        )
        # The placeholder refuses before invoking the Store callback. This
        # local classification prevents Broker SDK fallback rules from turning
        # the refusal into an Accepted or execution-unknown order.
        error.code = "managed_ctp_write_composition_unavailable"
        error.managed_local_reject = True
        error.definite_reject = True
        raise error

    def submit_order(self, order: Any, sdk_dispatch: Callable[[Any], Any]) -> Any:
        """Reject without invoking the SDK dispatch callback."""

        self._reject()

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        sdk_dispatch: Callable[[Any], Any],
    ) -> Any:
        """Reject without invoking the SDK dispatch callback."""

        self._reject()


def _info_value(order: Any, name: str) -> Any:
    info = getattr(order, "info", None)
    getter = getattr(info, "get", None)
    return getter(name) if callable(getter) else None


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ManagedExecutionBindingError("invalid " + field_name)
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ManagedExecutionBindingError("invalid " + field_name) from error
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise ManagedExecutionBindingError("invalid " + field_name)
    return decimal_value


def _finite_decimal(value: Any, field_name: str) -> Decimal:
    """Parse an exact monetary fact without assuming its sign.

    A venue fee can be negative for a maker rebate, so fill accounting may not
    apply the strictly-positive quantity/price rule to commission evidence.
    """

    if isinstance(value, bool):
        raise ManagedExecutionBindingError("invalid " + field_name)
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ManagedExecutionBindingError("invalid " + field_name) from error
    if not decimal_value.is_finite():
        raise ManagedExecutionBindingError("invalid " + field_name)
    return decimal_value


def _required_info_text(order: Any, name: str) -> str:
    value = _info_value(order, name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManagedExecutionBindingError("managed order is missing " + name)
    return value


def _managed_runtime_order_id(scope: Any, intent_id: str) -> str:
    """Derive a bounded provider reservation identity from durable SDK identity.

    ``ExecutionScope.key`` is a stable digest over provider, environment,
    account reference, strategy, and trading day.  The SDK execution journal
    keys records by that scope plus ``intent_id``.  Hashing the same pair with
    a Backtrader-owned domain/version prefix gives CTP's separate durable
    OrderRef reservation the same restart identity without using ``Order.ref``.
    """

    scope_key = getattr(scope, "key", None)
    if (
        not isinstance(scope_key, str)
        or len(scope_key) != 70
        or not scope_key.startswith("scope:")
        or any(character not in "0123456789abcdef" for character in scope_key[6:])
    ):
        raise ManagedExecutionBindingError("managed runtime scope key is not canonical")
    if not isinstance(intent_id, str) or not intent_id or intent_id != intent_id.strip():
        raise ManagedExecutionBindingError("managed intent identity is invalid")
    digest = hashlib.sha256(
        b"backtrader.managed.runtime-order-id.v1\0"
        + scope_key.encode("utf-8")
        + b"\0"
        + intent_id.encode("utf-8")
    ).hexdigest()
    return "bt-managed-v1:" + digest


def _order_price(order: Any) -> Any:
    direct = getattr(order, "price", None)
    if direct not in (None, 0, 0.0):
        return direct
    created = getattr(order, "created", None)
    return getattr(created, "price", None)


def _order_quantity(order: Any) -> Any:
    direct = getattr(order, "size", None)
    if direct not in (None, 0, 0.0):
        try:
            return abs(direct)
        except TypeError:
            return direct
    created = getattr(order, "created", None)
    size = getattr(created, "size", None)
    if size is None:
        return None
    try:
        return abs(size)
    except TypeError:
        return size


@dataclass(frozen=True)
class _CanonicalManagedOrder:
    """The exact framework facts that the legacy Store will turn into a write.

    ``order.info`` is strategy-controlled metadata.  It may name an intent,
    but it must never be allowed to describe a safer order than the Backtrader
    object which the legacy Store will eventually serialize.  This small value
    object is constructed from the same order fields used by
    ``BtApiStore._order_to_payload`` and is checked both before durable risk
    admission and immediately before the private legacy dispatcher is called.
    """

    instrument: str
    side: Any
    is_buy: bool
    quantity: Decimal
    price: Decimal
    position_effect: Any
    reduce_only: bool
    metadata_digest: str
    quantity_unit: Optional[str]
    exectype: Any
    order_ref: Any
    valid: Any
    tradeid: Any
    provider_info: Mapping[str, Any]


@dataclass(frozen=True)
class _ProviderProjectionPreApplyFacts:
    """Broker state and expected incremental facts captured before mutation."""

    quantity: Decimal
    prior_source_quantity: Decimal
    average_price: Decimal
    commission: Decimal
    execution_bit_count: int
    incremental_quantity: Optional[float]
    incremental_price: Optional[float]
    incremental_commission: Optional[float]


def _payload_data_name(order: Any) -> str:
    """Return the data-name selection used by ``BtApiStore._order_to_payload``."""

    data = getattr(order, "data", None)
    value = (
        getattr(data, "_name", None)
        or getattr(data, "_dataname", None)
        or getattr(getattr(data, "p", None), "dataname", None)
        or getattr(data, "_dataname", None)
        or repr(data)
    )
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManagedExecutionBindingError("managed order data symbol is not provable")
    return value


def _payload_quantity(order: Any) -> Any:
    """Return the exact quantity source the legacy Store serializes."""

    value = getattr(order, "size", None)
    try:
        return abs(value)
    except TypeError:
        return value


def _payload_limit_price(order: Any) -> Any:
    """Mirror the legacy Store's limit-price selection without importing it."""

    price = getattr(order, "price", None)
    created = getattr(order, "created", None)
    created_price = getattr(created, "price", None)
    if price is None:
        price = created_price
    if price is not None:
        try:
            if float(price) <= 0:
                price = created_price if created_price is not None else None
        except (TypeError, ValueError):
            # Decimal validation below produces the public, deterministic
            # managed-route error.  Do not guess a replacement price here.
            pass
    return price


def _actual_limit_side(order: Any, execution: Any) -> Any:
    """Derive one unambiguous side from the actual Backtrader order."""

    isbuy = getattr(order, "isbuy", None)
    issell = getattr(order, "issell", None)
    if not callable(isbuy) or not callable(issell):
        raise ManagedExecutionBindingError("managed order side is not provable")
    buy = isbuy()
    sell = issell()
    if buy is True and sell is False:
        return execution.Side.BUY
    if sell is True and buy is False:
        return execution.Side.SELL
    raise ManagedExecutionBindingError("managed order side is not provable")


def _position_effect_offset(effect: Any) -> str:
    """Map an SDK position effect to the exact legacy Store payload offset."""

    value = getattr(effect, "value", effect)
    mapping = {
        "OPEN": "open",
        "CLOSE": "close",
        "CLOSE_TODAY": "close_today",
        "CLOSE_YESTERDAY": "close_yesterday",
    }
    try:
        return mapping[value]
    except (KeyError, TypeError) as error:
        raise ManagedExecutionBindingError("invalid managed_position_effect") from error


def _runtime_is_live(runtime: Any) -> bool:
    """Return whether this bridge is guarding a live managed contract."""

    contract = getattr(runtime, "contract", None)
    return (
        bool(getattr(contract, "is_managed_live", False))
        or getattr(contract, "mode", None) == "live"
    )


def _sealed_quantity_unit(runtime: Any, instrument: str, metadata_digest: str) -> Optional[str]:
    """Read quantity semantics only from the sealed runtime snapshot.

    ``order.info`` is strategy-controlled and must never select whether a
    numeric quantity means base units, contracts, or another venue unit.  The
    direct managed SDK composition installs one immutable snapshot on every
    live runtime; replay runtimes may intentionally have no snapshot.
    """

    snapshot = getattr(runtime, "instrument_metadata_snapshot", None)
    live = _runtime_is_live(runtime)
    if snapshot is None:
        if live:
            raise ManagedExecutionBindingError(
                "managed live runtime lacks a sealed instrument metadata snapshot"
            )
        return None

    record_for = getattr(snapshot, "instrument_metadata", None)
    digest_for = getattr(snapshot, "instrument_digest", None)
    if not callable(record_for) or not callable(digest_for):
        raise ManagedExecutionBindingError(
            "managed runtime metadata snapshot cannot prove instrument quantity semantics"
        )
    try:
        record = record_for(instrument)
        expected_digest = digest_for(instrument)
    except Exception as error:
        raise ManagedExecutionBindingError(
            "managed instrument is absent from the sealed metadata snapshot"
        ) from error
    if not isinstance(expected_digest, str) or metadata_digest != expected_digest:
        raise ManagedExecutionBindingError(
            "managed instrument metadata digest does not match the sealed snapshot"
        )
    unit = getattr(record, "quantity_unit", None)
    if unit is None and not live:
        return None
    if not isinstance(unit, str) or not unit or unit != unit.strip():
        raise ManagedExecutionBindingError(
            "managed live metadata lacks a canonical instrument quantity_unit"
        )
    return unit


def _frozen_order_scalar(value: Any, field_name: str, *, allow_none: bool = False) -> Any:
    """Reject mutable framework values before they enter a provider projection."""

    if value is None and allow_none:
        return None
    if type(value) in (str, int, float, Decimal):
        return value
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value
    raise ManagedExecutionBindingError("managed order has unsupported " + field_name)


def _optional_provider_text(order: Any, name: str) -> Optional[str]:
    """Copy one scalar Store payload field without retaining mutable order.info."""

    value = _info_value(order, name)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManagedExecutionBindingError("invalid managed provider field " + name)
    return value


def _optional_provider_scalar(order: Any, name: str) -> Any:
    value = _info_value(order, name)
    if value is None:
        return None
    return _frozen_order_scalar(value, "provider field " + name)


def _canonical_provider_info(
    order: Any,
    *,
    offset: str,
    reduce_only: bool,
    quantity_unit: Optional[str],
    runtime_order_id: Optional[str],
) -> Mapping[str, Any]:
    """Freeze every Store-recognized execution-shaping ``order.info`` field.

    The legacy Store maps only this finite set of fields into its provider
    payload.  A managed bridge deliberately copies those values before risk
    admission and later dispatches a proxy with this mapping, rather than the
    mutable framework order.  Fields with no sealed meaning at this boundary
    are rejected instead of being allowed to override durable idempotency or
    unit semantics.
    """

    if _info_value(order, "quantity_unit") is not None:
        raise ManagedExecutionBindingError(
            "managed order quantity_unit must come from sealed instrument metadata"
        )
    if _info_value(order, "client_order_id") is not None:
        raise ManagedExecutionBindingError(
            "managed order client_order_id is owned by the durable execution runtime"
        )
    if _info_value(order, "runtime_order_id") is not None:
        raise ManagedExecutionBindingError(
            "managed order runtime_order_id is derived from its durable scope and intent"
        )
    if _info_value(order, "exchange_id") is not None:
        raise ManagedExecutionBindingError(
            "managed order exchange_id requires a sealed venue-routing contract"
        )

    result: dict[str, Any] = {
        "offset": offset,
        "reduce_only": reduce_only,
    }
    if quantity_unit is not None:
        result["quantity_unit"] = quantity_unit

    position_mode = _optional_provider_text(order, "position_mode")
    if position_mode is not None:
        if position_mode != "net":
            raise ManagedExecutionBindingError(
                "managed order position_mode requires a typed position-leg contract"
            )
        result["position_mode"] = position_mode

    time_in_force = _optional_provider_text(order, "time_in_force")
    if time_in_force is not None:
        if time_in_force.upper() != "GTC":
            raise ManagedExecutionBindingError(
                "managed order time_in_force requires a typed execution policy"
            )
        result["time_in_force"] = time_in_force

    # These identity fields are already validated by the CTP/Broker layer when
    # that layer owns them.  Preserve only immutable scalar copies so no
    # strategy callback can substitute one after risk admission.
    for name in (
        "position_side",
        "position_id",
        "execution_cycle_id",
        "execution_role",
        "strategy_identity_sha256",
    ):
        value = _optional_provider_text(order, name)
        if value is not None:
            result[name] = value
    # The SDK durable CTP reservation is keyed by authenticated venue/account/
    # strategy identity plus this stable scope-and-intent digest.
    if runtime_order_id is not None:
        result["runtime_order_id"] = runtime_order_id
    for name in ("front_id", "session_id", "order_ref"):
        value = _optional_provider_scalar(order, name)
        if value is not None:
            result[name] = value
    return MappingProxyType(result)


class _CanonicalManagedOrderProxy:
    """Minimal immutable Backtrader-order shape accepted by the legacy Store.

    The Store needs only the attributes below to form its provider payload.
    It never receives the mutable source order once durable admission starts,
    closing the check-to-dispatch window for ``order.info`` and order fields.
    """

    __slots__ = (
        "created",
        "data",
        "exectype",
        "info",
        "price",
        "pricelimit",
        "ref",
        "size",
        "tradeid",
        "valid",
        "_is_buy",
    )

    def __init__(self, canonical: _CanonicalManagedOrder) -> None:
        self.ref = canonical.order_ref
        self.exectype = canonical.exectype
        self.data = SimpleNamespace(_name=canonical.instrument)
        self.price = canonical.price
        self.pricelimit = None
        self.created = SimpleNamespace(price=canonical.price)
        self._is_buy = canonical.is_buy
        self.size = canonical.quantity if self._is_buy else -canonical.quantity
        self.valid = canonical.valid
        self.tradeid = canonical.tradeid
        self.info = canonical.provider_info

    def isbuy(self) -> bool:
        return self._is_buy

    def issell(self) -> bool:
        return not self._is_buy

    @staticmethod
    def getordername() -> str:
        return "Limit"


def _canonical_managed_order_from_order(order: Any, runtime: Any) -> _CanonicalManagedOrder:
    """Validate metadata against the actual order which the Store will write."""

    execution = getattr(runtime, "execution", None)
    if execution is None:
        raise ManagedExecutionBindingError("managed runtime lacks execution contracts")
    if _required_info_text(order, "managed_order_type") != "LIMIT":
        raise ManagedExecutionBindingError(
            "managed route currently supports only explicit LIMIT orders"
        )
    # Keep normal Backtrader imports out of module import time.  This function
    # only runs after a reviewed managed runtime has already been composed.
    try:
        from backtrader.order import OrderBase
    except Exception as error:
        raise ManagedExecutionBindingError(
            "Backtrader limit-order contract is unavailable"
        ) from error
    if getattr(order, "exectype", None) != OrderBase.Limit:
        raise ManagedExecutionBindingError("managed route requires Backtrader Order.Limit")

    instrument = _required_info_text(order, "managed_instrument")
    intent_id = _required_info_text(order, "managed_intent_id")
    scope = getattr(runtime, "scope", None)
    provider = getattr(scope, "provider", None)
    runtime_order_id = (
        _managed_runtime_order_id(scope, intent_id)
        if isinstance(provider, str) and provider.strip().upper() == "CTP"
        else None
    )
    actual_instrument = _payload_data_name(order)
    if actual_instrument != instrument:
        raise ManagedExecutionBindingError(
            "managed instrument does not match the Backtrader order data symbol"
        )
    metadata_digest = _required_info_text(order, "managed_instrument_metadata_digest")
    quantity_unit = _sealed_quantity_unit(runtime, actual_instrument, metadata_digest)

    effect_name = _required_info_text(order, "managed_position_effect")
    try:
        effect = execution.PositionEffect(effect_name)
    except (TypeError, ValueError) as error:
        raise ManagedExecutionBindingError("invalid managed_position_effect") from error
    expected_offset = _position_effect_offset(effect)
    offset = _info_value(order, "offset")
    if offset != expected_offset:
        raise ManagedExecutionBindingError(
            "managed position effect does not match the Backtrader order offset"
        )
    expected_reduce_only = expected_offset != "open"
    reduce_only = _info_value(order, "reduce_only")
    if type(reduce_only) is not bool or reduce_only is not expected_reduce_only:
        raise ManagedExecutionBindingError(
            "managed position effect does not match the Backtrader order reduce_only flag"
        )
    if getattr(order, "pricelimit", None) is not None:
        raise ManagedExecutionBindingError(
            "managed route requires one canonical limit price without pricelimit"
        )
    side = _actual_limit_side(order, execution)
    is_buy = side == execution.Side.BUY
    if not is_buy and side != execution.Side.SELL:
        raise ManagedExecutionBindingError("managed order side is not provable")
    valid = _frozen_order_scalar(getattr(order, "valid", None), "valid", allow_none=True)
    tradeid = _frozen_order_scalar(getattr(order, "tradeid", 0), "tradeid")
    order_ref = _frozen_order_scalar(getattr(order, "ref", None), "reference")

    return _CanonicalManagedOrder(
        instrument=actual_instrument,
        side=side,
        is_buy=is_buy,
        quantity=_positive_decimal(_payload_quantity(order), "managed quantity"),
        price=_positive_decimal(_payload_limit_price(order), "managed limit price"),
        position_effect=effect,
        reduce_only=reduce_only,
        metadata_digest=metadata_digest,
        quantity_unit=quantity_unit,
        exectype=getattr(order, "exectype", None),
        order_ref=order_ref,
        valid=valid,
        tradeid=tradeid,
        provider_info=_canonical_provider_info(
            order,
            offset=expected_offset,
            reduce_only=reduce_only,
            quantity_unit=quantity_unit,
            runtime_order_id=runtime_order_id,
        ),
    )


def _assert_intent_matches_canonical_order(
    order: Any, intent: Any, runtime: Any
) -> _CanonicalManagedOrder:
    """Reject any drift between durable admission and the outgoing payload."""

    if getattr(intent, "scope", None) != getattr(runtime, "scope", None):
        raise ManagedExecutionBindingError(
            "managed admitted intent scope does not match runtime scope"
        )
    canonical = _canonical_managed_order_from_order(order, runtime)
    fields = (
        ("instrument", canonical.instrument),
        ("side", canonical.side),
        ("quantity", canonical.quantity),
        ("price", canonical.price),
        ("position_effect", canonical.position_effect),
        ("reduce_only", canonical.reduce_only),
    )
    for name, expected in fields:
        if getattr(intent, name, None) != expected:
            raise ManagedExecutionBindingError(
                "managed admitted intent does not match Backtrader order " + name
            )
    if getattr(intent, "intent_id", None) != _required_info_text(order, "managed_intent_id"):
        raise ManagedExecutionBindingError(
            "managed admitted intent does not match Backtrader order intent_id"
        )
    if getattr(intent, "signal_id", None) != _required_info_text(order, "managed_signal_id"):
        raise ManagedExecutionBindingError(
            "managed admitted intent does not match Backtrader order signal_id"
        )
    if getattr(intent, "metadata_version", None) != _required_info_text(
        order, "managed_metadata_version"
    ):
        raise ManagedExecutionBindingError(
            "managed admitted intent does not match Backtrader order metadata_version"
        )
    tags = getattr(intent, "tags", None)
    if (
        not isinstance(tags, Mapping)
        or tags.get("instrument_metadata_digest") != canonical.metadata_digest
    ):
        raise ManagedExecutionBindingError(
            "managed admitted intent does not match Backtrader instrument metadata digest"
        )
    if canonical.quantity_unit is not None and tags.get("quantity_unit") != canonical.quantity_unit:
        raise ManagedExecutionBindingError(
            "managed admitted intent does not match sealed instrument quantity_unit"
        )
    return canonical


def strict_limit_intent_from_order(order: Any, runtime: Any) -> Any:
    """Map one explicitly annotated Backtrader limit order to an execution intent.

    The framework alone cannot prove a stable signal identity, execution
    metadata version, native quantity semantics, or a CTP close effect.  The
    adapter therefore requires those reviewed values in ``order.info`` instead
    of guessing from an order reference or silently treating every sell as a
    close.  ``managed_order_type=LIMIT`` also stops stop/market/bracket/OCO
    orders from degrading into ordinary provider writes.
    """

    execution = getattr(runtime, "execution", None)
    scope = getattr(runtime, "scope", None)
    if execution is None or scope is None:
        raise ManagedExecutionBindingError("managed runtime lacks execution contracts")
    canonical = _canonical_managed_order_from_order(order, runtime)
    intent = execution.OrderIntent.limit(
        intent_id=_required_info_text(order, "managed_intent_id"),
        scope=scope,
        signal_id=_required_info_text(order, "managed_signal_id"),
        instrument=canonical.instrument,
        side=canonical.side,
        quantity=canonical.quantity,
        price=canonical.price,
        position_effect=canonical.position_effect,
        reduce_only=canonical.reduce_only,
        metadata_version=_required_info_text(order, "managed_metadata_version"),
        # The bridge does not construct or infer instrument facts.  A reviewed
        # composition root must bind the exact metadata digest to the
        # framework order, so an instrument-aware admission gate can reject a
        # stale or substituted quantity/fee/tick profile before dispatch.
        tags={
            # A Backtrader reference is process-local and changes when a
            # crashed runtime materializes the same durable intent again.
            # Keeping it in the intent fingerprint would make the SDK reject
            # the only safe recovery path as a conflicting duplicate.
            "instrument_metadata_digest": canonical.metadata_digest,
            **(
                {"quantity_unit": canonical.quantity_unit}
                if canonical.quantity_unit is not None
                else {}
            ),
        },
    )
    _assert_intent_matches_canonical_order(order, intent, runtime)
    return intent


def observation_from_store_response(runtime: Any, intent: Any, response: Any) -> Any:
    """Turn only explicit provider acceptance/rejection evidence into an observation.

    Anything else is deliberately raised to the durable execution facade,
    which records the dispatch result as ``UNKNOWN`` and never resends it.
    """

    execution = getattr(runtime, "execution", None)
    if execution is None or not isinstance(response, Mapping):
        raise ManagedExecutionBindingError("provider response is not managed execution evidence")
    status = str(response.get("status") or response.get("order_status") or "").strip().lower()
    if response.get("execution_unknown") is True:
        raise ManagedExecutionBindingError("provider response is execution-unknown")
    if status in {"rejected", "reject", "failed", "error"}:
        return execution.ProviderObservation.rejected(intent.intent_id, "provider_rejected")
    provider_order_id = next(
        (
            response.get(key)
            for key in ("id", "order_id", "orderId", "ordId", "external_order_id")
            if response.get(key) not in (None, "")
        ),
        None,
    )
    if isinstance(provider_order_id, bool) or not isinstance(provider_order_id, (str, int)):
        raise ManagedExecutionBindingError("provider acceptance lacks order identity")
    provider_order_id = str(provider_order_id).strip()
    if not provider_order_id:
        raise ManagedExecutionBindingError("provider acceptance lacks order identity")
    if status in {"accepted", "submitted", "open", "success", "ok"}:
        return execution.ProviderObservation.accepted(intent.intent_id, provider_order_id)
    if status in {"partial", "partially_filled", "filled"}:
        # A legacy provider payload is not enough evidence to fabricate a fill.
        # The provider adapter must normalize both quantities explicitly before
        # this bridge can write a durable partial/full execution state.  Missing
        # or inconsistent evidence raises here; the execution facade then marks
        # the one attempted dispatch UNKNOWN instead of pretending it is merely
        # ACKED and losing fill progress.
        filled_quantity = _positive_decimal(
            response.get("filled_quantity"), "managed filled_quantity"
        )
        average_price = _positive_decimal(response.get("average_price"), "managed average_price")
        # The durable execution record currently carries fill quantity and
        # average price, but no atomic Backtrader accounting receipt.  The
        # direct, first-dispatch response is therefore the only automatic
        # projection path and must include its exact cumulative fee fact.  Do
        # not let a managed fill silently fall back to a local commission-rate
        # estimate; ambiguous evidence is converted by the facade to UNKNOWN.
        cumulative_commission = _finite_decimal(
            response.get("cumulative_commission"), "managed cumulative_commission"
        )
        expected_quantity = _positive_decimal(
            getattr(intent, "quantity", None), "managed intent quantity"
        )
        if filled_quantity > expected_quantity:
            raise ManagedExecutionBindingError("managed filled_quantity exceeds intent quantity")
        if status in {"partial", "partially_filled"}:
            if filled_quantity >= expected_quantity:
                raise ManagedExecutionBindingError(
                    "managed partial fill must be below intent quantity"
                )
            state = execution.ExecutionState.PARTIALLY_FILLED
        else:
            if filled_quantity != expected_quantity:
                raise ManagedExecutionBindingError(
                    "managed filled quantity must equal intent quantity"
                )
            state = execution.ExecutionState.FILLED
        try:
            return execution.ProviderObservation(
                intent.intent_id,
                state,
                provider_order_id=provider_order_id,
                filled_quantity=filled_quantity,
                average_price=average_price,
                cumulative_commission=cumulative_commission,
            )
        except TypeError:
            # Older isolated fixture doubles intentionally expose the prior
            # execution contract.  They cannot take part in durable framework
            # projection recovery, but retaining their shape keeps the normal
            # no-I/O bridge tests focused on their stated boundary.
            return execution.ProviderObservation(
                intent.intent_id,
                state,
                provider_order_id=provider_order_id,
                filled_quantity=filled_quantity,
                average_price=average_price,
            )
    raise ManagedExecutionBindingError("provider response is not confirmed execution evidence")


def strict_cancel_intent_from_order(order: Any, runtime: Any) -> Any:
    """Map one annotated Backtrader order to a journal-bound cancellation.

    The Store never uses a bare framework reference as a cancellation
    authority.  The original managed intent id comes from reviewed order
    metadata; the provider order identity is then loaded from the same scoped
    durable execution record that confirmed the original submission.  A stable
    cancellation id is derived from that immutable target unless a reviewed
    explicit ``managed_cancel_intent_id`` is present.
    """

    execution = getattr(runtime, "execution", None)
    scope = getattr(runtime, "scope", None)
    execution_store = getattr(runtime, "execution_store", None)
    if execution is None or scope is None or execution_store is None:
        raise ManagedExecutionBindingError("managed runtime lacks cancellation contracts")
    target_intent_id = _required_info_text(order, "managed_intent_id")
    target = execution_store.get(target_intent_id, scope=scope)
    if target is None:
        raise ManagedExecutionBindingError("managed cancellation target intent is unknown")
    provider_order_id = getattr(target, "provider_order_id", None)
    if not isinstance(provider_order_id, str) or not provider_order_id.strip():
        raise ManagedExecutionBindingError(
            "managed cancellation target lacks confirmed provider identity"
        )
    declared_provider_order_id = _info_value(order, "managed_provider_order_id")
    if declared_provider_order_id not in (None, ""):
        if (
            not isinstance(declared_provider_order_id, str)
            or declared_provider_order_id.strip() != provider_order_id
        ):
            raise ManagedExecutionBindingError(
                "managed cancellation provider identity does not match durable target"
            )
    cancel_id = _info_value(order, "managed_cancel_intent_id")
    if cancel_id in (None, ""):
        cancel_id = "cancel." + target_intent_id
    if not isinstance(cancel_id, str) or cancel_id != cancel_id.strip():
        raise ManagedExecutionBindingError("invalid managed_cancel_intent_id")
    try:
        return execution.CancelIntent(
            cancel_id=cancel_id,
            scope=scope,
            target_intent_id=target_intent_id,
            provider_order_id=provider_order_id,
            metadata_version=_required_info_text(order, "managed_metadata_version"),
            # As with submissions, a local framework ref is not stable across
            # process recovery and must not become cancellation identity.
            tags={},
        )
    except Exception as error:
        raise ManagedExecutionBindingError("invalid managed cancellation intent") from error


def cancel_observation_from_store_response(runtime: Any, intent: Any, response: Any) -> Any:
    """Convert only explicit, target-identified provider cancellation evidence.

    The legacy Store's cancellation response may be permissive for historic
    callers.  A managed route is deliberately stricter: no response may become
    an acknowledgement unless it repeats the target provider order identity
    exactly.  Ambiguity reaches the durable facade as ``UNKNOWN``.
    """

    execution = getattr(runtime, "execution", None)
    if execution is None or not isinstance(response, Mapping):
        raise ManagedExecutionBindingError("provider response is not cancellation evidence")
    if response.get("execution_unknown") is True:
        raise ManagedExecutionBindingError("provider response is cancellation-unknown")
    provider_order_id = next(
        (
            response.get(key)
            for key in (
                "provider_order_id",
                "id",
                "order_id",
                "orderId",
                "ordId",
                "external_order_id",
            )
            if response.get(key) not in (None, "")
        ),
        None,
    )
    if isinstance(provider_order_id, bool) or not isinstance(provider_order_id, (str, int)):
        raise ManagedExecutionBindingError("provider cancellation lacks target order identity")
    provider_order_id = str(provider_order_id).strip()
    if not provider_order_id or provider_order_id != getattr(intent, "provider_order_id", None):
        raise ManagedExecutionBindingError("provider cancellation target identity mismatch")
    status = str(response.get("status") or response.get("order_status") or "").strip().lower()
    if status in {"cancelled", "canceled"}:
        return execution.CancelObservation.cancelled(
            intent.cancel_id, intent.target_intent_id, provider_order_id
        )
    if status in {
        "accepted",
        "submitted",
        "open",
        "success",
        "ok",
        "pending",
        "pending_cancel",
        "cancel_requested",
        "cancel_submitted",
    }:
        return execution.CancelObservation.accepted(
            intent.cancel_id, intent.target_intent_id, provider_order_id
        )
    if status in {"rejected", "reject", "failed", "error", "denied"}:
        return execution.CancelObservation.rejected(
            intent.cancel_id,
            intent.target_intent_id,
            provider_order_id,
            "provider_cancel_rejected",
        )
    raise ManagedExecutionBindingError("provider response is not confirmed cancellation evidence")


def project_record_to_store_response(record: Any, provider_response: Any) -> Mapping[str, Any]:
    """Project durable execution state to the existing Broker response shape."""

    state = str(getattr(getattr(record, "state", None), "value", ""))
    if state in {"ACKED", "PARTIALLY_FILLED", "FILLED"}:
        if isinstance(provider_response, Mapping):
            return dict(provider_response)
        # A repeated intent is resolved from the durable journal and deliberately
        # does not call the Store's provider port again.  Preserve that safe
        # idempotency at the framework boundary by reconstructing only the
        # confirmed provider identity recorded by the execution facade.
        provider_order_id = getattr(record, "provider_order_id", None)
        if isinstance(provider_order_id, bool) or not isinstance(provider_order_id, (str, int)):
            return {
                "status": "rejected",
                "error_code": "managed_execution_missing_provider_identity",
                "error_msg": "Managed execution record lacks a confirmed provider order identity.",
                "managed_execution_state": state,
            }
        provider_order_id = str(provider_order_id).strip()
        if not provider_order_id:
            return {
                "status": "rejected",
                "error_code": "managed_execution_missing_provider_identity",
                "error_msg": "Managed execution record lacks a confirmed provider order identity.",
                "managed_execution_state": state,
            }
        status = {
            "ACKED": "accepted",
            "PARTIALLY_FILLED": "partial",
            "FILLED": "filled",
        }[state]
        response = {
            "status": status,
            "id": provider_order_id,
            "managed_execution_replayed": True,
            "managed_execution_state": state,
        }
        if state in {"PARTIALLY_FILLED", "FILLED"}:
            response["filled_quantity"] = str(getattr(record, "filled_quantity", ""))
            average_price = getattr(record, "average_price", None)
            if average_price is not None:
                response["average_price"] = str(average_price)
            cumulative_commission = getattr(record, "cumulative_commission", None)
            if cumulative_commission is not None:
                response["cumulative_commission"] = str(cumulative_commission)
        return response
    if state == "UNKNOWN":
        return {
            "status": "submitted",
            "execution_unknown": True,
            "error_code": str(getattr(record, "unknown_reason", "") or "managed_execution_unknown"),
            # A direct ambiguous reply keeps the one framework order alive for
            # reconciliation.  A later durable replay belongs to a fresh
            # framework order and must be blocked by BtApiBroker just like a
            # replayed confirmed fill: there is no persisted projection receipt
            # proving which local order owns that uncertain provider attempt.
            "managed_execution_replayed": provider_response is None,
            "managed_execution_state": state,
        }
    return {
        "status": "rejected",
        "error_code": "managed_execution_" + (state.lower() or "unconfirmed"),
        "error_msg": "Managed execution did not confirm a provider submission.",
        "managed_execution_state": state or "UNCONFIRMED",
    }


def project_cancel_record_to_store_response(
    record: Any, provider_response: Any
) -> Mapping[str, Any]:
    """Project a durable cancellation result to the legacy Store response shape.

    A provider ACK says only that a cancellation command was received.  It is
    not a Backtrader terminal state: the original mapping must remain available
    for a late fill or a separately reconciled terminal update.  Mark every
    non-terminal managed result explicitly so ``BtApiBroker`` cannot take its
    historic optimistic-local-cancel branch.
    """

    state = str(getattr(getattr(record, "state", None), "value", ""))
    provider_order_id = getattr(record, "provider_order_id", None)
    if state in {"ACKED", "CANCELLED"}:
        if isinstance(provider_response, Mapping):
            response = dict(provider_response)
            if state == "ACKED":
                # Do not pass a permissive legacy ``accepted`` response to
                # the Broker as if it were enough to cancel locally.
                response["status"] = "cancel_requested"
                response["managed_execution_cancel_pending"] = True
                response["managed_execution_cancel_state"] = state
                response["managed_execution_cancel_reconciliation_required"] = True
            else:
                # The durable cancellation state is the terminal authority.
                # Do not let a legacy response spelling (or a stale provider
                # echo) route this record through the Broker's optimistic
                # cancellation branch as an arbitrary non-terminal response.
                response["status"] = "cancelled"
            return response
        if not isinstance(provider_order_id, str) or not provider_order_id.strip():
            return {
                "status": "rejected",
                "error_code": "managed_cancel_missing_provider_identity",
                "error_msg": "Managed cancellation record lacks a confirmed provider order identity.",
                "managed_execution_cancel_state": state,
                "managed_execution_cancel_pending": True,
                "managed_execution_cancel_reconciliation_required": True,
            }
        response = {
            "status": "cancel_requested" if state == "ACKED" else "cancelled",
            "id": provider_order_id,
            "managed_execution_cancel_replayed": True,
            "managed_execution_cancel_state": state,
        }
        if state == "ACKED":
            response["managed_execution_cancel_pending"] = True
            response["managed_execution_cancel_reconciliation_required"] = True
        return response
    if state == "UNKNOWN":
        return {
            "status": "submitted",
            "execution_unknown": True,
            "error_code": str(getattr(record, "unknown_reason", "") or "managed_cancel_unknown"),
            "managed_execution_cancel_state": state,
            "managed_execution_cancel_pending": True,
            "managed_execution_cancel_reconciliation_required": True,
            "managed_execution_cancel_freeze_required": True,
        }
    return {
        "status": "rejected",
        "error_code": "managed_cancel_" + (state.lower() or "unconfirmed"),
        "error_msg": "Managed execution did not confirm provider cancellation.",
        "managed_execution_cancel_state": state or "UNCONFIRMED",
        "managed_execution_cancel_pending": True,
        "managed_execution_cancel_reconciliation_required": True,
    }


@dataclass
class ManagedExecutionBridge:
    """Adapt framework orders to a previously composed durable execution runtime."""

    runtime: Any
    intent_from_order: Callable[[Any, Any], Any] = strict_limit_intent_from_order
    observation_from_response: Callable[[Any, Any, Any], Any] = observation_from_store_response
    response_from_record: Callable[[Any, Any], Mapping[str, Any]] = project_record_to_store_response
    cancel_intent_from_order: Callable[[Any, Any], Any] = strict_cancel_intent_from_order
    cancel_observation_from_response: Callable[[Any, Any, Any], Any] = (
        cancel_observation_from_store_response
    )
    cancel_response_from_record: Callable[[Any, Any], Mapping[str, Any]] = (
        project_cancel_record_to_store_response
    )
    provider_observation_from_update: Optional[Callable[[Any, Any, Mapping[str, Any]], Any]] = None
    _cancellation_facade: Any = field(default=None, init=False, repr=False)
    _framework_projection_journal: Optional[FrameworkProjectionJournal] = field(
        default=None, init=False, repr=False
    )
    _framework_projection_claims: dict[str, FrameworkProjectionClaim] = field(
        default_factory=dict, init=False, repr=False
    )
    _source_event_claims: dict[str, FrameworkSourceEventClaim] = field(
        default_factory=dict, init=False, repr=False
    )
    _source_event_pre_apply_facts: dict[str, _ProviderProjectionPreApplyFacts] = field(
        default_factory=dict, init=False, repr=False
    )
    _source_event_last_facts: dict[str, tuple[Decimal, Optional[Decimal], Optional[Decimal]]] = (
        field(default_factory=dict, init=False, repr=False)
    )
    _source_replay_orders: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _source_replay_events: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _deferred_fee_events: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _source_projection_blocked: bool = field(default=False, init=False, repr=False)
    _interrupted_cancellation_recovery_pending: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            not callable(getattr(self.runtime, "submit", None))
            or getattr(self.runtime, "scope", None) is None
        ):
            raise ManagedExecutionBindingError("a composed managed execution runtime is required")
        if not all(
            callable(callback)
            for callback in (
                self.intent_from_order,
                self.observation_from_response,
                self.response_from_record,
                self.cancel_intent_from_order,
                self.cancel_observation_from_response,
                self.cancel_response_from_record,
            )
        ):
            raise ManagedExecutionBindingError("managed bridge callbacks must be callable")
        try:
            self._framework_projection_journal = self._create_framework_projection_journal()
            self._register_framework_projection_closeable()
            self._recover_interrupted_cancellation_dispatches(defer_if_writer_unavailable=True)
            self._recover_unknown_cancellation_freezes()
        except Exception:
            self.close()
            raise

    def get_strategy_allocation(self, strategy_id: str) -> Any:
        """Read this strategy's local risk allocation without provider I/O.

        The optional SDK reader returns its immutable reservation-ledger
        snapshot. Its notional amounts are neither account cash nor margin,
        and a sizing observation does not reserve or authorize an order.
        """

        scope = self.runtime.scope
        if (
            type(strategy_id) is not str
            or not strategy_id
            or strategy_id != getattr(scope, "strategy_id", None)
        ):
            raise ManagedExecutionBindingError("allocation strategy does not match runtime scope")
        risk_scope = getattr(self.runtime, "risk_scope", None)
        reader = getattr(getattr(self.runtime, "risk_gate", None), "get_strategy_allocation", None)
        if risk_scope is None or not callable(reader):
            raise ManagedExecutionBindingError("managed allocation reader is unavailable")
        snapshot = reader(risk_scope, strategy_id)
        if (
            getattr(snapshot, "scope", None) != risk_scope
            or getattr(snapshot, "strategy_id", None) != strategy_id
        ):
            raise ManagedExecutionBindingError("allocation snapshot does not match runtime scope")
        return snapshot

    def submit_order(self, order: Any, legacy_dispatch: Callable[[Any], Any]) -> Mapping[str, Any]:
        """Persist/admit an intent, then call the Store port only through the runtime facade."""

        self._ensure_interrupted_cancellation_recovery()
        if not callable(legacy_dispatch):
            raise ManagedExecutionBindingError("Store legacy dispatch port is unavailable")
        intent = self.intent_from_order(order, self.runtime)
        if getattr(intent, "scope", None) != self.runtime.scope:
            raise ManagedExecutionBindingError("managed intent scope does not match runtime scope")
        # The risk facade must receive an intent derived from the actual order
        # payload, not a friendlier set of ``order.info`` declarations.  This
        # is intentionally repeated in ``dispatch`` below because admission
        # hooks run between these two points and must not be able to mutate the
        # framework order or substitute the admitted intent before the private
        # Store port performs its provider write.
        canonical = _assert_intent_matches_canonical_order(order, intent, self.runtime)
        if self.provider_observation_from_update is not None:
            self._source_replay_orders[str(intent.intent_id)] = {
                "bt_order_ref": getattr(order, "ref", None),
                "data_name": canonical.instrument,
                "side": "buy" if canonical.is_buy else "sell",
                "external_order_id": None,
                "venue_order_id": None,
                "client_order_id": None,
                "runtime_order_id": None,
                "order_ref": None,
            }
        provider_response: list[Any] = []

        def dispatch(admitted_intent: Any) -> Any:
            current = _assert_intent_matches_canonical_order(order, admitted_intent, self.runtime)
            if current != canonical:
                raise ManagedExecutionBindingError(
                    "managed provider projection changed after risk admission"
                )
            # Pass only the sealed snapshot to the legacy Store.  The source
            # Backtrader object remains mutable to the strategy and observers,
            # so rechecking it immediately above alone would leave a race
            # before ``_order_to_payload`` reads its fields.
            response = legacy_dispatch(_CanonicalManagedOrderProxy(canonical))
            provider_response.append(response)
            return self.observation_from_response(self.runtime, admitted_intent, response)

        record = self.runtime.submit(intent, dispatch)
        response = provider_response[0] if provider_response else None
        projected = self.response_from_record(record, response)
        if self.managed_provider_projection_enabled and str(
            getattr(getattr(record, "state", None), "value", "")
        ) in {"ACKED", "PARTIALLY_FILLED", "FILLED"}:
            # Never turn an ExecutionRecord into historical fill facts. The
            # Broker stays uncertain until the exact immutable outbox rows are
            # pulled and applied through the receipt path below.
            return {
                "status": "accepted",
                "id": str(getattr(record, "provider_order_id", "") or ""),
                "execution_unknown": True,
                "managed_execution_state": str(
                    getattr(getattr(record, "state", None), "value", "")
                ),
                "managed_provider_outbox_replay_pending": True,
            }
        claim = self._claim_framework_projection(intent, canonical, record)
        if claim is None:
            return projected
        result = dict(projected)
        # The receipt id is a non-secret lookup token only.  The active claim
        # token stays in this bridge so a strategy/provider response cannot
        # forge permission to make the Broker book a durable replay.
        result["managed_framework_projection_receipt_id"] = claim.receipt_id
        result["managed_framework_projection_state"] = claim.state
        return result

    def validate_framework_projection(self, response: Any, order: Any) -> bool:
        """Prove that this exact Broker order owns a live fill receipt.

        ``BtApiBroker`` calls this before it lets a durable replay reach its
        ordinary position/commission path.  A response flag by itself is never
        sufficient because legacy/provider payloads are not an authority for a
        framework recovery receipt.
        """

        if self._source_projection_blocked:
            return False
        claim = self._framework_projection_claim(response)
        journal = self._framework_projection_journal
        if claim is None or journal is None or not journal.validate(claim):
            return False
        try:
            intent = self.intent_from_order(order, self.runtime)
            canonical = _assert_intent_matches_canonical_order(order, intent, self.runtime)
            return (
                getattr(intent, "intent_id", None) == claim.intent_id
                and getattr(intent, "fingerprint", None) == claim.intent_fingerprint
                and canonical_framework_projection_fingerprint(canonical)
                == claim.canonical_fingerprint
            )
        except (FrameworkProjectionRecoveryError, ManagedExecutionBindingError):
            return False

    def complete_framework_projection(self, response: Any, order: Any) -> None:
        """Commit the local receipt only after Broker fill accounting succeeds."""

        claim = self._framework_projection_claim(response)
        journal = self._framework_projection_journal
        if (
            claim is None
            or journal is None
            or not self.validate_framework_projection(response, order)
        ):
            raise ManagedExecutionBindingError("managed framework projection receipt is not active")
        self._assert_framework_projection_execution(order, claim)
        try:
            journal.complete(claim)
        except FrameworkProjectionRecoveryError as error:
            raise ManagedExecutionBindingError(
                "managed framework projection receipt could not be completed"
            ) from error

    def fail_framework_projection(self, response: Any, reason: str) -> None:
        """Fence this process after a submit-path Broker apply is uncertain."""

        self._source_projection_blocked = True
        self._fence_source_projection_identity(reason)

    @property
    def managed_provider_projection_enabled(self) -> bool:
        """Whether this bridge was explicitly injected for durable callback projection."""

        return bool(
            self.provider_observation_from_update is not None
            and self._framework_projection_journal is not None
            and callable(
                getattr(
                    getattr(self.runtime, "facade", None), "record_provider_observation_event", None
                )
            )
            and callable(
                getattr(getattr(self.runtime, "execution_store", None), "read_outbox", None)
            )
        )

    def poll_managed_provider_outbox_update(self) -> Optional[Mapping[str, Any]]:
        """Read the next exact scoped source event after the local durable cursor.

        The cursor is session-local: a new Broker session starts at sequence
        zero and reconstructs its empty in-memory state from immutable outbox
        rows. Known intent lifecycle rows are recorded as consumed no-ops;
        unknown event types and missing order mappings stop the stream.
        """

        if not self.managed_provider_projection_enabled or self._source_projection_blocked:
            return None
        journal = self._framework_projection_journal
        assert journal is not None
        try:
            identity = self.runtime.execution_store.journal_source_identity()
            generation = self._execution_journal_generation(identity)
            scope_key = getattr(self.runtime.scope, "key", None)
            session_id = self.runtime.framework_projection_session_id
            known_lifecycle_events = {
                "intent_recorded",
                "intent_admitted",
                "dispatch_claimed",
                "intent_rejected",
                "intent_blocked",
                "dispatch_blocked",
            }
            projectable_events = {
                "provider_observation",
                "reconciled_observation",
                "provider_commission_evidence",
                "cancelled_by_cancel_intent",
            }
            # Bound work per Broker poll. A later call resumes at the durable
            # cursor if the page contains only lifecycle facts.
            for _ in range(100):
                after_sequence = journal.source_high_water(
                    scope_key=scope_key,
                    journal_incarnation_id=generation,
                    session_id=session_id,
                )
                page = self.runtime.execution_store.read_outbox(
                    after_sequence=after_sequence,
                    limit=100,
                    scope=self.runtime.scope,
                )
                if not isinstance(page, (tuple, list)):
                    raise ManagedExecutionBindingError("source outbox page is invalid")
                if not page:
                    return None
                event = page[0]
                if (
                    getattr(event, "scope_key", None) != scope_key
                    or getattr(event, "journal_incarnation_id", None) != generation
                ):
                    raise ManagedExecutionBindingError(
                        "source outbox event does not match the execution journal identity"
                    )
                event_type = getattr(event, "event_type", None)
                if event_type in known_lifecycle_events:
                    self._validate_no_fill_lifecycle_event(event)
                    journal.advance_source_event(
                        event=event,
                        session_id=session_id,
                        expected_scope_key=scope_key,
                    )
                    continue
                if event_type not in projectable_events:
                    raise ManagedExecutionBindingError(
                        "source outbox contains an unsupported event type"
                    )
                self._validate_projectable_source_event(event)
                intent_id = getattr(event, "intent_id", None)
                deferred = self._deferred_fee_events.get(intent_id)
                if deferred is event or (
                    deferred is not None
                    and getattr(deferred, "event_id", None) == getattr(event, "event_id", None)
                ):
                    later_page = self.runtime.execution_store.read_outbox(
                        after_sequence=event.sequence,
                        limit=100,
                        scope=self.runtime.scope,
                    )
                    later_event = None
                    for candidate in later_page:
                        candidate_type = getattr(candidate, "event_type", None)
                        if candidate_type in known_lifecycle_events:
                            self._validate_no_fill_lifecycle_event(candidate)
                            continue
                        if candidate_type in projectable_events:
                            self._validate_projectable_source_event(candidate)
                            if self._event_supersedes_fee_pending(event, candidate):
                                later_event = candidate
                                break
                            if self._event_can_wait_for_fee_evidence(event, candidate):
                                continue
                        break
                    if later_event is None or not self._event_supersedes_fee_pending(
                        event, later_event
                    ):
                        return None
                    journal.advance_source_event(
                        event=event,
                        session_id=session_id,
                        expected_scope_key=scope_key,
                    )
                    self._deferred_fee_events.pop(intent_id, None)
                    continue
                mapping = self._source_replay_orders.get(intent_id)
                if mapping is None:
                    # Do not step past another order's earlier event. Its
                    # strategy order must first be materialized in this fresh
                    # Broker session.
                    return None
                event_id = getattr(event, "event_id", None)
                if not isinstance(event_id, str) or not event_id:
                    raise ManagedExecutionBindingError("source outbox event id is invalid")
                self._source_replay_events[event_id] = event
                original = dict(mapping)
                original.update(
                    kind="order",
                    status="accepted",
                    managed_provider_outbox_event_id=event_id,
                )
                return self._provider_event_broker_update(event, original)
            return None
        except Exception as error:
            self._fence_source_projection_identity("source_outbox_recovery_failure")
            if isinstance(error, ManagedExecutionBindingError):
                raise
            raise ManagedExecutionBindingError(
                "durable provider source outbox is unavailable"
            ) from error

    def prepare_managed_provider_projection(
        self, update: Mapping[str, Any], order: Any
    ) -> Optional[Mapping[str, Any]]:
        """Persist, claim and normalize one callback before Broker mutation.

        The injected normalizer is the only raw-provider boundary. The facade
        must return the exact immutable event appended by its SQLite transaction;
        this method never joins a newer execution record to an older event.
        """

        if not self.managed_provider_projection_enabled:
            raise ManagedExecutionBindingError(
                "durable managed provider projection was not explicitly injected"
            )
        if self._source_projection_blocked:
            raise ManagedExecutionBindingError("managed provider projection session is fenced")
        journal = self._framework_projection_journal
        assert journal is not None
        try:
            intent = self.intent_from_order(order, self.runtime)
            canonical = _assert_intent_matches_canonical_order(order, intent, self.runtime)
            replay_event_id = update.get("managed_provider_outbox_event_id")
            if isinstance(replay_event_id, str):
                event = self._source_replay_events.get(replay_event_id)
                if event is None:
                    raise ManagedExecutionBindingError(
                        "durable provider outbox event is no longer available"
                    )
                if getattr(event, "intent_id", None) != getattr(intent, "intent_id", None):
                    raise ManagedExecutionBindingError(
                        "durable provider event intent does not match the framework order"
                    )
                return self._claim_provider_event(event, update, order, canonical)

            callback = self.provider_observation_from_update
            assert callback is not None
            observation = callback(self.runtime, intent, update)
            observation_type = getattr(
                getattr(self.runtime, "execution", None), "ProviderObservation", None
            )
            if observation_type is None or not isinstance(observation, observation_type):
                raise ManagedExecutionBindingError(
                    "provider update normalizer returned no typed observation"
                )
            if getattr(observation, "intent_id", None) != getattr(intent, "intent_id", None):
                raise ManagedExecutionBindingError(
                    "provider observation intent does not match the framework order"
                )
            event = self.runtime.facade.record_provider_observation_event(observation)
            # Even when this append is new, only the scoped outbox reader may
            # advance it. That orders it behind any earlier durable events.
            if event is None:
                return None
            self._validate_event_against_observation(event, observation, intent)
            event_id = getattr(event, "event_id", None)
            if not isinstance(event_id, str) or not event_id:
                raise ManagedExecutionBindingError("immutable provider event id is invalid")
            self._source_replay_events[event_id] = event
            return None
        except ManagedExecutionBindingError as error:
            if not bool(getattr(error, "provider_projection_retryable", False)):
                self._fence_source_projection_identity("source_observation_preparation_failure")
            raise
        except FrameworkProjectionRecoveryError as error:
            self._fence_source_projection_identity("source_event_journal_failure")
            raise ManagedExecutionBindingError(
                "managed provider source event could not be claimed"
            ) from error
        except Exception as error:
            self._fence_source_projection_identity("source_observation_preparation_failure")
            raise ManagedExecutionBindingError(
                "managed provider event could not be durably prepared"
            ) from error

    def validate_managed_provider_projection(self, update: Any, order: Any) -> bool:
        """Prove a prepared provider event still owns its private local receipt."""

        if not isinstance(update, Mapping) or self._source_projection_blocked:
            return False
        receipt_id = update.get("_managed_provider_projection_receipt_id")
        if not isinstance(receipt_id, str):
            return False
        claim = self._source_event_claims.get(receipt_id)
        journal = self._framework_projection_journal
        if claim is None or journal is None or not journal.validate_source_event(claim):
            return False
        pre_apply = self._source_event_pre_apply_facts.get(claim.receipt_id)
        if pre_apply is None:
            return False
        status_by_state = {
            "ACKED": "accepted",
            "PARTIALLY_FILLED": "partial",
            "FILLED": "completed",
            "CANCELLED": "canceled",
            "REJECTED": "rejected",
        }
        try:
            if (
                update.get("managed_source_event_id") != claim.event_id
                or update.get("managed_source_event_sequence") != claim.sequence
                or update.get("managed_source_event_type") != claim.event_type
                or update.get("status") != status_by_state[claim.state]
                or self._source_decimal(update.get("filled")) != claim.filled_quantity
                or self._source_optional_decimal(update.get("managed_source_average_price"))
                != claim.average_price
                or self._source_optional_decimal(update.get("managed_source_cumulative_commission"))
                != claim.cumulative_commission
                or "avg_price" in update
                or "cumulative_commission" in update
                or update.get("price")
                != (
                    pre_apply.incremental_price
                    if pre_apply.incremental_price is not None
                    else (
                        self._source_binary64(claim.average_price, "source cumulative average")
                        if claim.average_price is not None
                        else 0.0
                    )
                )
                or update.get("commission") != (pre_apply.incremental_commission or 0.0)
                or update.get("commission_normalized") is not True
                or update.get("order_id") != claim.provider_order_id
            ):
                return False
        except (KeyError, ManagedExecutionBindingError):
            return False
        try:
            intent = self.intent_from_order(order, self.runtime)
            canonical = _assert_intent_matches_canonical_order(order, intent, self.runtime)
            return getattr(
                intent, "intent_id", None
            ) == claim.intent_id and canonical_framework_projection_fingerprint(
                canonical
            ) == self._source_event_order_fingerprint(claim)
        except (FrameworkProjectionRecoveryError, ManagedExecutionBindingError):
            return False

    def complete_managed_provider_projection(self, update: Any, order: Any) -> None:
        """Complete the local source high-water after successful Broker accounting."""

        claim = self._source_event_claim(update)
        journal = self._framework_projection_journal
        if (
            claim is None
            or journal is None
            or not self.validate_managed_provider_projection(update, order)
        ):
            raise ManagedExecutionBindingError("managed provider event receipt is not active")
        pre_apply = self._source_event_pre_apply_facts.get(claim.receipt_id)
        if pre_apply is None:
            raise ManagedExecutionBindingError("managed provider pre-apply facts are unavailable")
        self._assert_provider_event_execution(order, claim, pre_apply)
        try:
            journal.complete_source_event(claim)
        except FrameworkProjectionRecoveryError as error:
            self._fence_source_projection(claim, "post_apply_receipt_failure")
            raise ManagedExecutionBindingError(
                "managed provider event receipt could not be completed"
            ) from error
        self._source_event_claims.pop(claim.receipt_id, None)
        self._source_event_pre_apply_facts.pop(claim.receipt_id, None)
        self._source_event_last_facts[claim.intent_id] = (
            claim.filled_quantity,
            claim.average_price,
            claim.cumulative_commission,
        )
        self._source_replay_events.pop(claim.event_id, None)

    def fail_managed_provider_projection(self, update: Any, reason: str) -> None:
        """Fence this session if Broker apply was interrupted or became uncertain."""

        claim = self._source_event_claim(update)
        if claim is not None:
            self._fence_source_projection(claim, reason)

    def _fence_source_projection(self, claim: FrameworkSourceEventClaim, reason: str) -> None:
        self._source_projection_blocked = True
        journal = self._framework_projection_journal
        if journal is not None:
            try:
                journal.fence_source_session(
                    scope_key=claim.scope_key,
                    journal_incarnation_id=claim.journal_incarnation_id,
                    session_id=claim.session_id,
                    reason=reason,
                )
            except FrameworkProjectionRecoveryError:
                # The in-memory latch still fences this process if the journal
                # itself is what failed.
                pass

    def _fence_source_projection_identity(self, reason: str) -> None:
        self._source_projection_blocked = True
        journal = self._framework_projection_journal
        if journal is None:
            return
        identity_reader = getattr(self.runtime.execution_store, "journal_source_identity", None)
        if not callable(identity_reader):
            return
        try:
            identity = identity_reader()
            incarnation = (
                identity.get("generation")
                if isinstance(identity, Mapping)
                else getattr(identity, "generation", None)
            )
            journal.fence_source_session(
                scope_key=self.runtime.scope.key,
                journal_incarnation_id=incarnation,
                session_id=self.runtime.framework_projection_session_id,
                reason=reason,
            )
        except Exception:
            pass

    def _source_event_claim(self, update: Any) -> Optional[FrameworkSourceEventClaim]:
        if not isinstance(update, Mapping):
            return None
        receipt_id = update.get("_managed_provider_projection_receipt_id")
        if not isinstance(receipt_id, str):
            return None
        return self._source_event_claims.get(receipt_id)

    def _claim_provider_event(
        self, event: Any, update: Mapping[str, Any], order: Any, canonical: Any
    ) -> Mapping[str, Any]:
        journal = self._framework_projection_journal
        assert journal is not None
        identity = self.runtime.execution_store.journal_source_identity()
        generation = self._execution_journal_generation(identity)
        scope_key = getattr(self.runtime.scope, "key", None)
        if (
            getattr(event, "scope_key", None) != scope_key
            or getattr(event, "journal_incarnation_id", None) != generation
            or getattr(event, "intent_id", None)
            != getattr(self.intent_from_order(order, self.runtime), "intent_id", None)
        ):
            raise ManagedExecutionBindingError(
                "immutable source event identity changed before claim"
            )
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            raise ManagedExecutionBindingError("immutable source event payload is invalid")
        filled = self._source_decimal(payload.get("filled_quantity"))
        average_raw = payload.get("average_price")
        commission_raw = payload.get("cumulative_commission")
        executed = getattr(order, "executed", None)
        already_filled = abs(self._source_decimal(getattr(executed, "size", 0) or 0))
        already_average = self._source_decimal(getattr(executed, "price", 0) or 0)
        already_commission = self._source_decimal(getattr(executed, "comm", 0) or 0)
        intent_id = str(getattr(event, "intent_id"))
        previous_facts = self._source_event_last_facts.get(intent_id)
        if previous_facts is None:
            previous_quantity, previous_average, previous_commission = (
                Decimal("0"),
                None,
                Decimal("0"),
            )
        else:
            previous_quantity, previous_average, previous_commission = previous_facts
        if filled < previous_quantity:
            self._source_projection_blocked = True
            self._fence_source_projection_identity("source_quantity_moved_backwards")
            raise ManagedExecutionBindingError(
                "managed provider cumulative quantity moved backwards"
            )
        if previous_facts is None:
            broker_matches_previous = already_filled == 0
        else:
            broker_matches_previous = self._within_binary64_ulps(
                already_filled, previous_quantity, budget=1
            )
            if previous_average is not None:
                broker_matches_previous = broker_matches_previous and self._within_binary64_ulps(
                    already_average, previous_average, budget=2
                )
            if previous_commission is not None:
                broker_matches_previous = broker_matches_previous and self._within_binary64_ulps(
                    already_commission, previous_commission, budget=1
                )
        if not broker_matches_previous:
            self._reject_unrepresentable_source_event(
                "source_broker_checkpoint_diverged",
                "Broker facts diverged from the previous immutable source event",
            )
        source_quantity_grew = filled > previous_quantity
        if source_quantity_grew and average_raw is None:
            self._source_projection_blocked = True
            self._fence_source_projection_identity("source_fill_missing_average")
            raise ManagedExecutionBindingError(
                "managed provider fill lacks its event-time average price"
            )
        if source_quantity_grew and commission_raw is None:
            self._deferred_fee_events[str(getattr(event, "intent_id"))] = event
            error = ManagedExecutionBindingError(
                "managed provider fill awaits event-time cumulative fee evidence"
            )
            error.provider_projection_retryable = True
            raise error
        if previous_facts is None and filled == 0:
            event_average = self._source_optional_decimal(average_raw)
            event_commission = self._source_optional_decimal(commission_raw)
            changed_economics = event_average is not None or event_commission not in (
                None,
                Decimal("0"),
            )
            if changed_economics:
                self._reject_unrepresentable_source_event(
                    "same_quantity_economic_adjustment",
                    "same-quantity provider event requires an unsupported fee or price adjustment",
                )
        elif previous_facts is not None and filled == previous_quantity:
            event_average = self._source_optional_decimal(average_raw)
            event_commission = self._source_optional_decimal(commission_raw)
            changed_economics = (
                event_average != previous_average or event_commission != previous_commission
            )
            if changed_economics:
                self._reject_unrepresentable_source_event(
                    "same_quantity_economic_adjustment",
                    "same-quantity provider event requires an unsupported fee or price adjustment",
                )

        pre_apply = self._source_projection_pre_apply_facts(
            order=order,
            filled=filled,
            average_raw=average_raw,
            commission_raw=commission_raw,
            already_filled=already_filled,
            already_average=already_average,
            already_commission=already_commission,
            previous_quantity=previous_quantity,
            previous_average=previous_average,
            previous_commission=previous_commission,
        )
        try:
            claim = journal.claim_source_event(
                event=event,
                session_id=self.runtime.framework_projection_session_id,
                expected_scope_key=scope_key,
                canonical_fingerprint=canonical_framework_projection_fingerprint(canonical),
            )
        except FrameworkProjectionRecoveryError as error:
            self._fence_source_projection_identity("source_event_journal_failure")
            raise ManagedExecutionBindingError(
                "managed provider source event could not be claimed"
            ) from error
        if claim is None:
            return None
        self._source_event_pre_apply_facts[claim.receipt_id] = pre_apply
        projected = self._provider_event_broker_update(event, update)
        source_average = projected.pop("avg_price", None)
        source_commission = projected.pop("cumulative_commission", None)
        projected["managed_source_average_price"] = source_average
        projected["managed_source_cumulative_commission"] = source_commission
        projected["price"] = (
            pre_apply.incremental_price
            if pre_apply.incremental_price is not None
            else (
                self._source_binary64(
                    self._source_decimal(source_average), "source cumulative average"
                )
                if source_average is not None
                else 0.0
            )
        )
        projected["commission"] = pre_apply.incremental_commission or 0.0
        projected["commission_normalized"] = True
        projected["_managed_provider_projection_receipt_id"] = claim.receipt_id
        self._source_event_claims[claim.receipt_id] = claim
        return projected

    def _source_projection_pre_apply_facts(
        self,
        *,
        order: Any,
        filled: Decimal,
        average_raw: Any,
        commission_raw: Any,
        already_filled: Decimal,
        already_average: Decimal,
        already_commission: Decimal,
        previous_quantity: Decimal,
        previous_average: Optional[Decimal],
        previous_commission: Optional[Decimal],
    ) -> _ProviderProjectionPreApplyFacts:
        """Reject nonrepresentable economic deltas before touching Broker state."""

        executed = getattr(order, "executed", None)
        bits = getattr(executed, "exbits", None)
        if not isinstance(bits, (list, tuple, deque)):
            raise ManagedExecutionBindingError("Broker execution checkpoint is unavailable")
        try:
            bit_count = len(bits)
        except Exception as error:
            raise ManagedExecutionBindingError(
                "Broker execution checkpoint is unavailable"
            ) from error

        incremental_quantity: Optional[float] = None
        incremental_price: Optional[float] = None
        incremental_commission: Optional[float] = None
        if filled > previous_quantity:
            requested_quantity = abs(self._source_decimal(getattr(order, "size", None)))
            if filled > requested_quantity:
                self._reject_unrepresentable_source_event(
                    "source_quantity_exceeds_order",
                    "managed provider cumulative quantity exceeds the framework order",
                )
            filled_float = self._source_binary64(filled, "source cumulative quantity")
            current_quantity_float = abs(
                self._source_binary64(already_filled, "Broker cumulative quantity")
            )
            incremental_quantity = filled_float - current_quantity_float
            # BtApiBroker ignores cumulative quantity deltas at or below this
            # explicit threshold. Refuse them before it can silently no-op.
            if not math.isfinite(incremental_quantity) or incremental_quantity <= 1e-12:
                self._reject_unrepresentable_source_event(
                    "source_quantity_delta_unrepresentable",
                    "managed provider quantity increment is below Broker resolution",
                )
            source_quantity_delta = Fraction(filled) - Fraction(previous_quantity)
            if not self._within_binary64_fraction_ulps(
                source_quantity_delta, incremental_quantity, budget=1
            ):
                self._reject_unrepresentable_source_event(
                    "source_quantity_precision_lost",
                    "managed provider quantity delta is not preserved by Broker float arithmetic",
                )

            average = self._source_decimal(average_raw)
            if previous_quantity == 0:
                source_incremental_price = Fraction(average)
            else:
                if previous_average is None:
                    self._reject_unrepresentable_source_event(
                        "source_previous_average_missing",
                        "previous source fill lacks its immutable cumulative average",
                    )
                source_incremental_price = (
                    Fraction(filled) * Fraction(average)
                    - Fraction(previous_quantity) * Fraction(previous_average)
                ) / source_quantity_delta
            if source_incremental_price <= 0:
                self._reject_unrepresentable_source_event(
                    "source_incremental_price_unrepresentable",
                    "managed provider incremental price is not positive",
                )
            incremental_price = self._source_fraction_binary64(
                source_incremental_price, "source incremental price"
            )

            if commission_raw is None:
                self._reject_unrepresentable_source_event(
                    "source_cumulative_fee_missing",
                    "managed provider fill lacks cumulative fee evidence",
                )
            commission = self._source_decimal(commission_raw)
            prior_fee = previous_commission or Decimal("0")
            source_incremental_commission = Fraction(commission) - Fraction(prior_fee)
            incremental_commission = self._source_fraction_binary64(
                source_incremental_commission, "source incremental commission"
            )
        elif previous_quantity != filled:
            self._reject_unrepresentable_source_event(
                "source_quantity_checkpoint_mismatch",
                "managed provider checkpoint quantity differs from the prior source event",
            )

        return _ProviderProjectionPreApplyFacts(
            quantity=already_filled,
            prior_source_quantity=previous_quantity,
            average_price=already_average,
            commission=already_commission,
            execution_bit_count=bit_count,
            incremental_quantity=incremental_quantity,
            incremental_price=incremental_price,
            incremental_commission=incremental_commission,
        )

    def _reject_unrepresentable_source_event(self, reason: str, message: str) -> None:
        self._source_projection_blocked = True
        self._fence_source_projection_identity(reason)
        raise ManagedExecutionBindingError(message)

    @staticmethod
    def _source_binary64(value: Decimal, name: str) -> float:
        try:
            converted = float(value)
        except (OverflowError, TypeError, ValueError) as error:
            raise ManagedExecutionBindingError(f"{name} is outside Broker float range") from error
        if not math.isfinite(converted):
            raise ManagedExecutionBindingError(f"{name} is outside Broker float range")
        return converted

    @staticmethod
    def _source_fraction_binary64(value: Fraction, name: str) -> float:
        try:
            converted = float(value)
        except (OverflowError, TypeError, ValueError) as error:
            raise ManagedExecutionBindingError(f"{name} is outside Broker float range") from error
        if not math.isfinite(converted) or (value and converted == 0.0):
            raise ManagedExecutionBindingError(f"{name} is outside Broker float resolution")
        return converted

    @classmethod
    def _within_binary64_ulps(cls, actual: Decimal, expected: Decimal, *, budget: int) -> bool:
        """Allow at most a fixed count of adjacent binary64 representations."""

        try:
            actual_float = cls._source_binary64(actual, "Broker execution fact")
            expected_float = cls._source_binary64(expected, "source execution fact")
            return cls._binary64_ulps_between(actual_float, expected_float, budget=budget)
        except (ManagedExecutionBindingError, OverflowError, ValueError, struct.error):
            return False

    @classmethod
    def _within_binary64_fraction_ulps(
        cls, exact_value: Fraction, projected_float: float, *, budget: int
    ) -> bool:
        """Compare a source-exact rational delta with a proposed Broker float."""

        try:
            exact_float = float(exact_value)
            return cls._binary64_ulps_between(exact_float, projected_float, budget=budget)
        except (OverflowError, ValueError, struct.error):
            return False

    @staticmethod
    def _binary64_ulps_between(actual: float, expected: float, *, budget: int) -> bool:
        if not math.isfinite(actual) or not math.isfinite(expected):
            return False
        sign_bit = 1 << 63
        uint64_mask = (1 << 64) - 1

        def ordered_bits(value: float) -> int:
            bits = struct.unpack(">Q", struct.pack(">d", value))[0]
            if bits & sign_bit:
                return (~bits) & uint64_mask
            return bits | sign_bit

        return abs(ordered_bits(actual) - ordered_bits(expected)) <= budget

    def _validate_event_against_observation(
        self, event: Any, observation: Any, intent: Any
    ) -> None:
        self._validate_projectable_source_event(event)
        identity = self.runtime.execution_store.journal_source_identity()
        generation = self._execution_journal_generation(identity)
        payload = getattr(event, "payload", None)
        if (
            getattr(event, "journal_incarnation_id", None) != generation
            or getattr(event, "scope_key", None) != getattr(self.runtime.scope, "key", None)
            or getattr(event, "intent_id", None) != getattr(intent, "intent_id", None)
            or not isinstance(payload, Mapping)
        ):
            raise ManagedExecutionBindingError(
                "immutable provider event identity does not match the execution journal"
            )
        if (
            payload.get("provider_order_id") != getattr(observation, "provider_order_id", None)
            or self._source_decimal(payload.get("filled_quantity"))
            != self._source_decimal(getattr(observation, "filled_quantity", None))
            or self._source_optional_decimal(payload.get("average_price"))
            != self._source_optional_decimal(getattr(observation, "average_price", None))
            or self._source_optional_decimal(payload.get("cumulative_commission"))
            != self._source_optional_decimal(getattr(observation, "cumulative_commission", None))
            or getattr(getattr(event, "state", None), "value", None)
            != getattr(getattr(observation, "state", None), "value", None)
        ):
            raise ManagedExecutionBindingError(
                "immutable provider event differs from the normalized observation"
            )

    @staticmethod
    def _execution_journal_generation(identity: Any) -> str:
        """Validate the only journal lineage this projector currently accepts."""

        generation_kind = (
            identity.get("generation_kind")
            if isinstance(identity, Mapping)
            else getattr(identity, "generation_kind", None)
        )
        generation = (
            identity.get("generation")
            if isinstance(identity, Mapping)
            else getattr(identity, "generation", None)
        )
        epoch = (
            identity.get("epoch")
            if isinstance(identity, Mapping)
            else getattr(identity, "epoch", None)
        )
        if (
            generation_kind != "EXECUTION_JOURNAL"
            or not isinstance(generation, str)
            or len(generation) != 32
            or any(character not in "0123456789abcdef" for character in generation)
            or type(epoch) is not int
            or epoch != 1
        ):
            raise ManagedExecutionBindingError("source journal identity is invalid")
        return generation

    @staticmethod
    def _validate_no_fill_lifecycle_event(event: Any) -> None:
        """Accept only exact execution-store lifecycle events with no fill facts."""

        event_type = getattr(event, "event_type", None)
        state = getattr(getattr(event, "state", None), "value", getattr(event, "state", None))
        payload = getattr(event, "payload", None)
        expected = {
            "intent_recorded": ("PENDING_ADMISSION", {"payload_sha256"}),
            "intent_admitted": ("PENDING_DISPATCH", {"permit_reference"}),
            "dispatch_claimed": ("DISPATCHING", {"dispatch_attempt"}),
            # The execution store only emits these states before any provider
            # dispatch. Exact reason-only payloads make their no-fill meaning
            # explicit; added economic fields must go through projection.
            "intent_rejected": ("REJECTED", {"reason_code"}),
            "intent_blocked": ("BLOCKED", {"reason_code"}),
            # A dispatch guard can block only before the facade invokes its
            # dispatcher port. The distinct event is terminal no-fill evidence.
            "dispatch_blocked": ("BLOCKED", {"reason_code"}),
        }
        rule = expected.get(event_type)
        if rule is None or state != rule[0] or not isinstance(payload, Mapping):
            raise ManagedExecutionBindingError("source lifecycle event is not a known no-fill fact")
        if set(payload) != rule[1]:
            raise ManagedExecutionBindingError(
                "source lifecycle event has unexpected payload facts"
            )
        value = next(iter(payload.values()))
        if event_type == "intent_recorded":
            valid = (
                type(value) is str
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
            )
        elif event_type == "intent_admitted":
            valid = value is None or (type(value) is str and bool(value.strip()))
        elif event_type == "dispatch_claimed":
            valid = type(value) is int and value > 0
        else:
            valid = (
                type(value) is str
                and bool(value)
                and value.isascii()
                and value.replace("_", "").isalnum()
            )
        if not valid:
            raise ManagedExecutionBindingError("source lifecycle event payload is invalid")

    def _validate_projectable_source_event(self, event: Any) -> None:
        """Validate the exact immutable event schema before using economic facts."""

        event_type = getattr(event, "event_type", None)
        state = getattr(getattr(event, "state", None), "value", getattr(event, "state", None))
        payload = getattr(event, "payload", None)
        if event_type == "cancelled_by_cancel_intent":
            expected_keys = {
                "cancel_id",
                "provider_order_id",
                "source",
                "filled_quantity",
                "average_price",
                "cumulative_commission",
            }
            valid_states = {"CANCELLED"}
        elif event_type == "provider_commission_evidence":
            expected_keys = {
                "provider_order_id",
                "filled_quantity",
                "average_price",
                "cumulative_commission",
                "source",
            }
            valid_states = {"ACKED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}
        elif event_type in {"provider_observation", "reconciled_observation"}:
            expected_keys = {
                "provider_order_id",
                "filled_quantity",
                "average_price",
                "cumulative_commission",
                "reason_code",
                "source",
            }
            valid_states = {"ACKED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}
        else:
            raise ManagedExecutionBindingError("source event type is not projectable")
        if (
            state not in valid_states
            or not isinstance(payload, Mapping)
            or set(payload) != expected_keys
        ):
            raise ManagedExecutionBindingError("projectable source event schema is invalid")
        source = payload.get("source")
        if source not in {"provider", "reconcile"}:
            raise ManagedExecutionBindingError("projectable source event provenance is invalid")
        provider_order_id = payload.get("provider_order_id")
        if provider_order_id is not None and (
            type(provider_order_id) is not str or not provider_order_id.strip()
        ):
            raise ManagedExecutionBindingError("projectable source provider order id is invalid")
        if event_type == "cancelled_by_cancel_intent":
            cancel_id = payload.get("cancel_id")
            if type(cancel_id) is not str or not cancel_id.strip() or not provider_order_id:
                raise ManagedExecutionBindingError("projectable cancellation identity is invalid")

        def decimal_text(name: str, *, optional: bool) -> Optional[Decimal]:
            raw = payload.get(name)
            if raw is None and optional:
                return None
            if type(raw) is not str or not raw or len(raw) > 128:
                raise ManagedExecutionBindingError("projectable source decimal is invalid")
            value = self._source_decimal(raw)
            if format(value, "f") != raw:
                raise ManagedExecutionBindingError("projectable source decimal is noncanonical")
            return value

        quantity = decimal_text("filled_quantity", optional=False)
        average = decimal_text("average_price", optional=True)
        commission = decimal_text("cumulative_commission", optional=True)
        if quantity is None or quantity < 0:
            raise ManagedExecutionBindingError("projectable source quantity is invalid")
        if average is not None and average <= 0:
            raise ManagedExecutionBindingError("projectable source average price is invalid")
        if event_type == "provider_commission_evidence" and commission is None:
            raise ManagedExecutionBindingError("commission evidence lacks cumulative fee")
        if quantity > 0 and provider_order_id is None:
            raise ManagedExecutionBindingError("projectable fill lacks provider order identity")
        if "reason_code" in expected_keys:
            reason_code = payload.get("reason_code")
            if reason_code is not None and (
                type(reason_code) is not str
                or not reason_code.isascii()
                or not reason_code.replace("_", "").isalnum()
            ):
                raise ManagedExecutionBindingError("projectable source reason code is invalid")

    @staticmethod
    def _event_supersedes_fee_pending(previous: Any, later: Any) -> bool:
        if (
            getattr(later, "intent_id", None) != getattr(previous, "intent_id", None)
            or type(getattr(later, "sequence", None)) is not int
            or type(getattr(previous, "sequence", None)) is not int
            or later.sequence <= previous.sequence
            or getattr(later, "scope_key", None) != getattr(previous, "scope_key", None)
            or getattr(later, "journal_incarnation_id", None)
            != getattr(previous, "journal_incarnation_id", None)
            or getattr(later, "event_type", None)
            not in {
                "provider_commission_evidence",
                "provider_observation",
                "reconciled_observation",
            }
        ):
            return False
        old_payload = getattr(previous, "payload", None)
        new_payload = getattr(later, "payload", None)
        if not isinstance(old_payload, Mapping) or not isinstance(new_payload, Mapping):
            return False
        if (
            old_payload.get("provider_order_id") != new_payload.get("provider_order_id")
            or new_payload.get("average_price") is None
            or new_payload.get("cumulative_commission") is None
        ):
            return False
        try:
            return Decimal(str(new_payload.get("filled_quantity"))) >= Decimal(
                str(old_payload.get("filled_quantity"))
            )
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def _event_can_wait_for_fee_evidence(previous: Any, candidate: Any) -> bool:
        """Whether a later same-intent snapshot can be skipped after fee catch-up."""

        if (
            getattr(candidate, "intent_id", None) != getattr(previous, "intent_id", None)
            or type(getattr(candidate, "sequence", None)) is not int
            or type(getattr(previous, "sequence", None)) is not int
            or candidate.sequence <= previous.sequence
            or getattr(candidate, "scope_key", None) != getattr(previous, "scope_key", None)
            or getattr(candidate, "journal_incarnation_id", None)
            != getattr(previous, "journal_incarnation_id", None)
            or getattr(candidate, "event_type", None)
            not in {
                "provider_commission_evidence",
                "provider_observation",
                "reconciled_observation",
                "cancelled_by_cancel_intent",
            }
        ):
            return False
        state = getattr(
            getattr(candidate, "state", None), "value", getattr(candidate, "state", None)
        )
        if state not in {"ACKED", "PARTIALLY_FILLED", "FILLED", "CANCELLED"}:
            return False
        old_payload = getattr(previous, "payload", None)
        new_payload = getattr(candidate, "payload", None)
        if not isinstance(old_payload, Mapping) or not isinstance(new_payload, Mapping):
            return False
        if (
            old_payload.get("provider_order_id") != new_payload.get("provider_order_id")
            or new_payload.get("average_price") is None
        ):
            return False
        try:
            return Decimal(str(new_payload.get("filled_quantity"))) >= Decimal(
                str(old_payload.get("filled_quantity"))
            )
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def _source_decimal(value: Any) -> Decimal:
        if isinstance(value, bool):
            raise ManagedExecutionBindingError("managed provider event decimal is invalid")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ManagedExecutionBindingError(
                "managed provider event decimal is invalid"
            ) from error
        if not result.is_finite():
            raise ManagedExecutionBindingError("managed provider event decimal is non-finite")
        return result

    @classmethod
    def _source_optional_decimal(cls, value: Any) -> Optional[Decimal]:
        return None if value is None else cls._source_decimal(value)

    @classmethod
    def _assert_provider_event_execution(
        cls,
        order: Any,
        claim: FrameworkSourceEventClaim,
        pre_apply: _ProviderProjectionPreApplyFacts,
    ) -> None:
        """Check rounded totals, actual incremental execution and terminal state."""

        executed = getattr(order, "executed", None)
        actual_quantity = abs(cls._source_decimal(getattr(executed, "size", None)))
        actual_average = cls._source_decimal(getattr(executed, "price", None))
        actual_commission = cls._source_decimal(getattr(executed, "comm", None))
        expected_average = claim.average_price or Decimal("0")
        expected_commission = claim.cumulative_commission or Decimal("0")
        if (
            not cls._within_binary64_ulps(actual_quantity, claim.filled_quantity, budget=1)
            or not cls._within_binary64_ulps(actual_average, expected_average, budget=2)
            or not cls._within_binary64_ulps(actual_commission, expected_commission, budget=1)
        ):
            raise ManagedExecutionBindingError(
                "Broker execution did not reach immutable provider event cumulative facts"
            )

        bits = getattr(executed, "exbits", None)
        if not isinstance(bits, (list, tuple, deque)):
            raise ManagedExecutionBindingError("Broker execution bits are unavailable")
        quantity_advanced = claim.filled_quantity > pre_apply.prior_source_quantity
        expected_bit_count = pre_apply.execution_bit_count + (1 if quantity_advanced else 0)
        if len(bits) != expected_bit_count:
            raise ManagedExecutionBindingError(
                "Broker execution did not append the claimed incremental fill"
            )
        if quantity_advanced:
            bit = bits[-1]
            bit_quantity = abs(cls._source_decimal(getattr(bit, "size", None)))
            bit_price = cls._source_decimal(getattr(bit, "price", None))
            bit_commission = cls._source_decimal(getattr(bit, "comm", None))
            assert pre_apply.incremental_quantity is not None
            assert pre_apply.incremental_price is not None
            assert pre_apply.incremental_commission is not None
            expected_bit_quantity = Decimal(str(pre_apply.incremental_quantity))
            expected_bit_price = Decimal(str(pre_apply.incremental_price))
            expected_bit_commission = Decimal(str(pre_apply.incremental_commission))
            if (
                bit_quantity != expected_bit_quantity
                or bit_price != expected_bit_price
                or (pre_apply.incremental_commission != 0.0 and bit_commission == 0)
                or not cls._within_binary64_ulps(bit_commission, expected_bit_commission, budget=1)
            ):
                raise ManagedExecutionBindingError(
                    "Broker incremental execution differs from the prepared source delta"
                )

        get_status_name = getattr(order, "getstatusname", None)
        if not callable(get_status_name):
            raise ManagedExecutionBindingError("Broker order status is unavailable")
        status = str(get_status_name()).lower()
        valid_statuses = {
            "ACKED": {"accepted"},
            "PARTIALLY_FILLED": {"partial", "completed"},
            "FILLED": {"completed"},
            "CANCELLED": {"canceled", "completed"},
            "REJECTED": {"rejected"},
        }.get(claim.state)
        if valid_statuses is None or status not in valid_statuses:
            raise ManagedExecutionBindingError(
                "Broker order status does not match the immutable provider event"
            )

    @staticmethod
    def _provider_event_broker_update(event: Any, original: Mapping[str, Any]) -> dict[str, Any]:
        raw_state = getattr(getattr(event, "state", None), "value", getattr(event, "state", None))
        status_by_state = {
            "ACKED": "accepted",
            "PARTIALLY_FILLED": "partial",
            "FILLED": "completed",
            "CANCELLED": "canceled",
            "REJECTED": "rejected",
        }
        if raw_state not in status_by_state:
            raise ManagedExecutionBindingError("immutable provider event has unsupported state")
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            raise ManagedExecutionBindingError("immutable provider event payload is invalid")
        projected = {
            key: original[key]
            for key in (
                "bt_order_ref",
                "data_name",
                "side",
                "external_order_id",
                "venue_order_id",
                "client_order_id",
                "runtime_order_id",
                "order_ref",
                "managed_provider_outbox_event_id",
            )
            if key in original
        }
        projected.update(
            kind="order",
            status=status_by_state[raw_state],
            filled=payload.get("filled_quantity"),
            avg_price=payload.get("average_price"),
            cumulative_commission=payload.get("cumulative_commission"),
            order_id=payload.get("provider_order_id"),
            managed_source_event_id=getattr(event, "event_id", None),
            managed_source_event_sequence=getattr(event, "sequence", None),
            managed_source_event_type=getattr(event, "event_type", None),
        )
        return projected

    def _source_event_order_fingerprint(self, claim: FrameworkSourceEventClaim) -> str:
        return claim.canonical_fingerprint

    def pending_framework_projection_intent_ids(self) -> tuple[str, ...]:
        """Return discovered projection checkpoints without provider activity."""

        journal = self._framework_projection_journal
        scope_key = getattr(getattr(self.runtime, "scope", None), "key", None)
        if journal is None or not isinstance(scope_key, str) or not scope_key:
            return ()
        return journal.pending_intent_ids(scope_key)

    def close(self) -> None:
        """Release only the bridge-owned framework projection journal handle."""

        journal = self._framework_projection_journal
        self._framework_projection_journal = None
        self._framework_projection_claims.clear()
        self._source_event_claims.clear()
        self._source_event_pre_apply_facts.clear()
        self._source_event_last_facts.clear()
        if journal is not None:
            journal.close()

    def _register_framework_projection_closeable(self) -> None:
        """Let a composed SDK runtime release the bridge receipt before its DBs.

        The normal SDK runtime owns the durable execution store lifecycle.  It
        exposes this narrow optional registration port so Backtrader can close
        its own independent SQLite receipt first without creating a reverse
        import from the SDK into the framework package.  Historical test
        doubles intentionally have no such lifecycle hook.
        """

        if self._framework_projection_journal is None:
            return
        register = getattr(self.runtime, "register_framework_projection_closeable", None)
        if register is None:
            return
        if not callable(register):
            raise ManagedExecutionBindingError(
                "managed runtime framework projection lifecycle hook is invalid"
            )
        try:
            register(self)
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed runtime could not register framework projection receipt"
            ) from error

    def _create_framework_projection_journal(self) -> Optional[FrameworkProjectionJournal]:
        """Open recovery durability only for a fully composed SDK runtime.

        Isolated bridge doubles intentionally predate the projection port and
        retain their established replay rejection behavior.  A real composed
        runtime has all four fields below; failure to open its journal is an
        admission failure, never a silent best-effort downgrade.
        """

        if (
            getattr(getattr(self.runtime, "contract", None), "preset", None)
            == "managed_live_gateway"
        ):
            # The gateway client intentionally has no direct framework fill
            # authority.  Its server-side projection requires a separately
            # reviewed transport/recovery contract and must not open or scan a
            # direct local receipt journal merely because a fake exposes a
            # similarly named state directory.
            return None
        state_directory = getattr(self.runtime, "state_directory", None)
        session_id = getattr(self.runtime, "framework_projection_session_id", None)
        facade = getattr(self.runtime, "facade", None)
        execution_store = getattr(self.runtime, "execution_store", None)
        present = (state_directory is not None, facade is not None, execution_store is not None)
        if not any(present):
            return None
        if not all(present) or not isinstance(session_id, str) or not session_id:
            raise ManagedExecutionBindingError(
                "managed composed runtime lacks framework projection recovery contract"
            )
        if not callable(getattr(facade, "acquire_writer_lease", None)) or not callable(
            getattr(execution_store, "assert_writer_lease", None)
        ):
            raise ManagedExecutionBindingError(
                "managed composed runtime lacks framework projection writer fence"
            )
        try:
            return FrameworkProjectionJournal(state_directory)
        except FrameworkProjectionRecoveryError as error:
            raise ManagedExecutionBindingError(
                "managed framework projection journal is unavailable"
            ) from error

    def _claim_framework_projection(
        self, intent: Any, canonical: _CanonicalManagedOrder, record: Any
    ) -> Optional[FrameworkProjectionClaim]:
        journal = self._framework_projection_journal
        if journal is None:
            return None
        state = str(getattr(getattr(record, "state", None), "value", ""))
        if state not in {"PARTIALLY_FILLED", "FILLED"}:
            return None
        session_id = getattr(self.runtime, "framework_projection_session_id", None)
        facade = getattr(self.runtime, "facade", None)
        execution_store = getattr(self.runtime, "execution_store", None)
        try:
            writer_lease = facade.acquire_writer_lease()
            execution_store.assert_writer_lease(self.runtime.scope, writer_lease)
            if getattr(intent, "fingerprint", None) != getattr(record, "payload_sha256", None):
                raise ManagedExecutionBindingError(
                    "managed framework projection record does not match admitted intent"
                )
            claim = journal.claim(
                record=record,
                canonical_fingerprint=canonical_framework_projection_fingerprint(canonical),
                session_id=session_id,
                lease_fencing_token=getattr(writer_lease, "fencing_token", None),
            )
        except ManagedExecutionBindingError:
            raise
        except Exception as error:
            # A fill without a durable framework recovery claim must not reach
            # Broker accounting.  It remains in the SDK journal for a later
            # reviewed recovery session instead of becoming an untracked local
            # position/commission mutation.
            raise ManagedExecutionBindingError(
                "managed framework projection recovery claim is unavailable"
            ) from error
        self._framework_projection_claims[claim.receipt_id] = claim
        return claim

    def _framework_projection_claim(self, response: Any) -> Optional[FrameworkProjectionClaim]:
        if not isinstance(response, Mapping):
            return None
        receipt_id = response.get("managed_framework_projection_receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            return None
        return self._framework_projection_claims.get(receipt_id)

    @staticmethod
    def _assert_framework_projection_execution(order: Any, claim: FrameworkProjectionClaim) -> None:
        """Check the ordinary Broker path booked exactly the durable checkpoint."""

        executed = getattr(order, "executed", None)
        try:
            executed_size = abs(_finite_decimal(getattr(executed, "size", None), "executed size"))
            executed_price = _positive_decimal(getattr(executed, "price", None), "executed price")
            executed_commission = _finite_decimal(
                getattr(executed, "comm", None), "executed commission"
            )
        except ManagedExecutionBindingError as error:
            raise ManagedExecutionBindingError(
                "managed framework projection did not produce complete Broker execution facts"
            ) from error
        if (
            executed_size != claim.filled_quantity
            or executed_price != claim.average_price
            or executed_commission != claim.cumulative_commission
        ):
            raise ManagedExecutionBindingError(
                "managed framework projection differs from durable fill evidence"
            )

    def cancel_order(
        self,
        order: Any,
        dataname: Optional[str],
        legacy_dispatch: Callable[[Any, Optional[str]], Any],
    ) -> Mapping[str, Any]:
        """Durably cancel one previously confirmed managed provider order.

        ``order`` must carry the original managed intent metadata.  A bare
        reference cannot enter this route because it cannot prove the target's
        strategy scope or durable provider identity.  The Store receives no
        exception-to-legacy fallback path from this method.
        """

        # Gateway submission deliberately discards the Store's legacy callback.
        # Cancellation has no corresponding sealed gateway command yet, so
        # passing this callback into the cancellation facade would silently
        # restore a direct provider route.  Keep that route unavailable until
        # an explicit typed gateway cancellation port is reviewed and bound.
        if (
            getattr(getattr(self.runtime, "contract", None), "preset", None)
            == "managed_live_gateway"
        ):
            raise ManagedExecutionBindingError(
                "MANAGED_GATEWAY_CANCEL_NOT_IMPLEMENTED: "
                "a sealed gateway cancellation dispatcher is required"
            )
        self._ensure_interrupted_cancellation_recovery()
        if not callable(legacy_dispatch):
            raise ManagedExecutionBindingError("Store legacy cancellation port is unavailable")
        intent = self.cancel_intent_from_order(order, self.runtime)
        if getattr(intent, "scope", None) != self.runtime.scope:
            raise ManagedExecutionBindingError(
                "managed cancellation scope does not match runtime scope"
            )
        provider_response: list[Any] = []

        def dispatch(admitted_intent: Any) -> Any:
            response = legacy_dispatch(admitted_intent.provider_order_id, dataname)
            provider_response.append(response)
            return self.cancel_observation_from_response(self.runtime, admitted_intent, response)

        record = self._get_cancellation_facade().cancel(intent, dispatch)
        if str(getattr(getattr(record, "state", None), "value", "")) == "UNKNOWN":
            self._freeze_unknown_cancellation(record)
        response = provider_response[0] if provider_response else None
        return self.cancel_response_from_record(record, response)

    def reconcile_cancel(self, observation: Any) -> Any:
        """Apply typed cancellation evidence without issuing a provider request."""

        self._ensure_interrupted_cancellation_recovery()
        record = self._get_cancellation_facade().reconcile(observation)
        if str(getattr(getattr(record, "state", None), "value", "")) == "UNKNOWN":
            self._freeze_unknown_cancellation(record)
        return record

    def resolve_confirmed_cancel_freeze(self, cancel_id: str) -> None:
        """Fail closed until a separately reviewed cancellation control port exists.

        A terminal cancellation observation cannot by itself establish account
        identity, monitor delivery, reconciliation completeness, and operator
        audit authorization.  Keeping this compatibility-shaped method as a
        deterministic rejection prevents a local caller from clearing an
        unknown-cancel safety latch through a convenience API.
        """

        raise ManagedExecutionBindingError(
            "CONTROLLED_CANCEL_FREEZE_RELEASE_REQUIRED: "
            "cancellation outcome freezes require an audited control port"
        )

    def create_cancellation_reconciliation_control(
        self,
        *,
        authorize: Callable[[Any], Any],
        clock: Optional[Callable[[], float]] = None,
    ) -> Any:
        """Create the explicit audited control port for one unknown cancellation.

        This opt-in composition hook intentionally has no convenience release
        method.  The returned SDK control port requires terminal typed
        cancellation evidence, a durable monitor-outbox fact, an
        identity-bound authorization decision, and a local audit command before
        it can clear one ``cancel-outcome-unknown`` freeze.  Gateway cancellation
        remains unsupported and cannot obtain this direct Store control path.
        """

        if not callable(authorize):
            raise ManagedExecutionBindingError("managed cancellation authorizer must be callable")
        self._ensure_interrupted_cancellation_recovery()
        if not self._supports_cancellation_reconciliation_control():
            raise ManagedExecutionBindingError(
                "MANAGED_CANCELLATION_CONTROL_ROUTE_UNSUPPORTED: "
                "only managed_live_direct or the exact offline fake replay cancellation route "
                "is implemented"
            )
        state_directory = getattr(self.runtime, "state_directory", None)
        if state_directory is None:
            raise ManagedExecutionBindingError(
                "managed runtime lacks a cancellation control state directory"
            )
        try:
            runtime_plugins = importlib.import_module("bt_api_py.runtime_plugins")
            factory = getattr(runtime_plugins, "ManagedCancellationReconciliationControlPort")
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed cancellation reconciliation control is unavailable"
            ) from error
        if not callable(factory):
            raise ManagedExecutionBindingError("managed cancellation control factory is invalid")
        try:
            return factory(
                self.runtime,
                self._get_cancellation_facade(),
                state_directory=state_directory,
                authorize=authorize,
                clock=clock,
            )
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed cancellation reconciliation control could not be composed"
            ) from error

    def _supports_cancellation_reconciliation_control(self) -> bool:
        """Recognize direct control and one exact registered offline fake identity.

        The offline replay exception is tied to the same scope tuple accepted
        by the SDK fake journal authority.  A production-shaped scope cannot
        borrow that local fake recovery contract.
        """

        contract = getattr(self.runtime, "contract", None)
        if getattr(contract, "preset", None) == "managed_live_direct":
            return True
        scope = getattr(self.runtime, "scope", None)
        risk_scope = getattr(self.runtime, "risk_scope", None)
        fake_authority = getattr(self.runtime, "fake_dispatch_authority", None)
        return (
            getattr(contract, "strategy_id", None) == "example.013_3.sa_midfreq_simnow"
            and getattr(contract, "mode", None) == "simulation"
            and getattr(contract, "preset", None) == "replay"
            and getattr(contract, "environment", None) == "offline"
            and getattr(contract, "order_route", None) == "managed_execution"
            and getattr(scope, "provider", None)
            == "iteration41_managed_replay_fake_provider"
            and getattr(scope, "environment", None) == "offline"
            and getattr(scope, "account_ref", None)
            == "iteration41_managed_replay_fake_account"
            and getattr(scope, "strategy_id", None) == getattr(contract, "strategy_id", None)
            and getattr(risk_scope, "provider", None) == "fake"
            and getattr(risk_scope, "environment", None) == "offline"
            and fake_authority is not None
        )

    def _get_cancellation_facade(self) -> Any:
        """Build one SDK cancellation facade only after the managed route is bound."""

        if self._cancellation_facade is not None:
            return self._cancellation_facade
        execution = getattr(self.runtime, "execution", None)
        execution_store = getattr(self.runtime, "execution_store", None)
        order_facade = getattr(self.runtime, "facade", None)
        acquire_writer_lease = getattr(order_facade, "acquire_writer_lease", None)
        factory = getattr(execution, "ManagedCancellationFacade", None)
        if execution_store is None or not callable(acquire_writer_lease) or not callable(factory):
            raise ManagedExecutionBindingError("managed runtime lacks cancellation durability")
        risk_gate = getattr(self.runtime, "risk_gate", None)
        risk_scope = getattr(self.runtime, "risk_scope", None)
        if risk_gate is None or risk_scope is None:
            raise ManagedExecutionBindingError("managed runtime lacks cancellation risk admission")
        try:
            risk = importlib.import_module("bt_api_risk")
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed cancellation risk package is unavailable"
            ) from error
        cancellation_risk_intent_id = self._cancellation_admission_risk_intent_id

        class _CancelRiskAdmission:
            def __init__(self, gate: Any, scope: Any) -> None:
                self._gate = gate
                self._scope = scope

            def _risk_intent(self, intent: Any) -> Any:
                return risk.RiskIntent(
                    # Risk reservations are account-wide, while execution
                    # cancellation ids are unique only inside an execution
                    # scope.  Keep the external cancellation id intact, but
                    # qualify this local reservation identity so sibling
                    # strategies cannot collide in one account journal.
                    intent_id=cancellation_risk_intent_id(intent),
                    scope=self._scope,
                    action=risk.IntentAction.CANCEL,
                    notional=Decimal("0"),
                    payload_fingerprint=intent.fingerprint,
                )

            def reserve(self, intent: Any) -> Any:
                return self._gate.reserve(self._risk_intent(intent))

            def validate(self, permit_reference: str, intent: Any) -> Any:
                return self._gate.validate_permit(permit_reference, self._risk_intent(intent))

            def claim_before_dispatch(self, permit_reference: str, intent: Any) -> Any:
                """Return proof that this exact cancel risk claim is durable."""
                risk_intent = self._risk_intent(intent)
                permit = self._gate.claim_for_dispatch(permit_reference, risk_intent)
                binding = self._gate.dispatch_claim_binding(permit_reference)
                binding_scope = getattr(binding, "scope", None)
                permit_scope = getattr(permit, "scope", None)
                if (
                    type(permit) is not risk.RiskPermit
                    or permit.permit_id != permit_reference
                    or permit.intent_id != risk_intent.intent_id
                    or getattr(permit_scope, "key", None) != self._scope.key
                    or permit.action is not risk.IntentAction.CANCEL
                    or permit.notional != Decimal("0")
                    or type(binding) is not risk.DispatchClaimBinding
                    or binding.permit_id != permit_reference
                    or getattr(binding_scope, "key", None) != self._scope.key
                    or binding.intent_id != risk_intent.intent_id
                    or binding.intent_hash != risk_intent.fingerprint
                    or binding.cause_id != "dispatch-inflight:" + risk_intent.intent_id
                ):
                    raise ManagedExecutionBindingError(
                        "risk gate did not confirm the exact cancellation dispatch claim"
                    )
                receipt_type = getattr(execution, "CancelDispatchClaimReceiptV1", None)
                if not isinstance(receipt_type, type):
                    raise ManagedExecutionBindingError(
                        "execution package lacks the cancellation claim receipt contract"
                    )
                return receipt_type(
                    permit_reference=permit_reference,
                    scope_key=intent.scope.key,
                    cancel_id=intent.cancel_id,
                    intent_fingerprint=intent.fingerprint,
                )

            def settle(self, permit_reference: str) -> Any:
                return self._gate.settle(permit_reference)

            def release(self, permit_reference: str, reason: str) -> None:
                self._gate.release(permit_reference, reason)

        self._cancellation_facade = factory(
            execution_store,
            self.runtime.scope,
            acquire_writer_lease=acquire_writer_lease,
            admission_gate=_CancelRiskAdmission(risk_gate, risk_scope),
        )
        return self._cancellation_facade

    def _supports_cancellation_recovery_contract(self) -> bool:
        """Limit cancellation recovery to direct and exact offline-fake runtimes."""

        contract = getattr(self.runtime, "contract", None)
        if getattr(contract, "preset", None) == "managed_live_direct":
            return True
        risk_scope = getattr(self.runtime, "risk_scope", None)
        return (
            getattr(contract, "mode", None) == "simulation"
            and getattr(contract, "preset", None) == "replay"
            and getattr(contract, "environment", None) == "offline"
            and getattr(contract, "order_route", None) == "managed_execution"
            and getattr(risk_scope, "provider", None) == "fake"
            and getattr(risk_scope, "environment", None) == "offline"
        )

    def _recover_unknown_cancellation_freezes(self) -> None:
        """Rebuild account freezes from all unresolved durable cancellations.

        An UNKNOWN cancellation is committed in the execution SQLite journal
        before this bridge can persist its independent risk SQLite latch. That
        is not a cross-store transaction. Under the account writer lease, scan
        every strategy scope for the account and reassert a freeze for each
        UNKNOWN or interrupted DISPATCHING cancellation before accepting a
        mutation. The scan is local only and never retries a provider request.
        """

        if not self._supports_cancellation_recovery_contract():
            return
        # Minimal test doubles can exercise order projection without the SDK
        # durability surface. Real composed runtimes provide a state directory.
        if getattr(self.runtime, "state_directory", None) is None:
            return
        if self._interrupted_cancellation_recovery_pending:
            # Retry both current-scope and account-wide recovery together once
            # the existing writer lease becomes available.
            return
        execution_store = getattr(self.runtime, "execution_store", None)
        scope = getattr(self.runtime, "scope", None)
        facade = getattr(self.runtime, "facade", None)
        risk_gate = getattr(self.runtime, "risk_gate", None)
        risk_scope = getattr(self.runtime, "risk_scope", None)
        list_unresolved = getattr(
            execution_store, "list_unresolved_cancellations_for_account", None
        )
        acquire_lease = getattr(facade, "acquire_writer_lease", None)
        assert_lease = getattr(execution_store, "assert_writer_lease", None)
        recover_interrupted = getattr(execution_store, "recover_interrupted_cancellations", None)
        get_cancel = getattr(execution_store, "get_cancel", None)
        freeze = getattr(risk_gate, "freeze", None)
        if (
            scope is None
            or risk_scope is None
            or not callable(list_unresolved)
            or not callable(acquire_lease)
            or not callable(assert_lease)
            or not callable(recover_interrupted)
            or not callable(get_cancel)
            or not callable(freeze)
        ):
            raise ManagedExecutionBindingError(
                "managed runtime lacks account cancellation recovery controls"
            )
        try:
            writer_lease = acquire_lease()
            assert_lease(scope, writer_lease)
            scoped_records = list_unresolved(scope, writer_lease=writer_lease)
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed account cancellation recovery journal could not be read under its lease"
            ) from error

        if not isinstance(scoped_records, tuple):
            raise ManagedExecutionBindingError(
                "managed account cancellation recovery returned invalid evidence"
            )
        for item in scoped_records:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ManagedExecutionBindingError(
                    "managed account cancellation recovery returned an invalid scope record"
                )
            source_scope, record = item
            source_scope_key = getattr(source_scope, "key", None)
            source_account_key = getattr(source_scope, "account_key", None)
            cancel_id = getattr(record, "cancel_id", None)
            state = getattr(getattr(record, "state", None), "value", None)
            if (
                not isinstance(source_scope_key, str)
                or not source_scope_key
                or source_account_key != getattr(scope, "account_key", None)
                or getattr(record, "scope_key", None) != source_scope_key
                or state not in {"DISPATCHING", "UNKNOWN"}
                or not isinstance(cancel_id, str)
                or not cancel_id
            ):
                raise ManagedExecutionBindingError(
                    "managed account cancellation recovery returned mismatched evidence"
                )

            if state == "DISPATCHING":
                try:
                    recover_interrupted(source_scope, writer_lease=writer_lease)
                    record = get_cancel(cancel_id, scope=source_scope)
                except Exception as error:
                    raise ManagedExecutionBindingError(
                        "managed account cancellation dispatch recovery failed"
                    ) from error
                if (
                    getattr(record, "scope_key", None) != source_scope_key
                    or getattr(getattr(record, "state", None), "value", None) != "UNKNOWN"
                    or getattr(record, "cancel_id", None) != cancel_id
                ):
                    raise ManagedExecutionBindingError(
                        "managed account cancellation dispatch recovery was not confirmed"
                    )

            cause_id = "cancel-outcome-unknown:" + source_scope_key + ":" + cancel_id
            try:
                freeze(risk_scope, cause_id, cause_id)
                if cause_id not in risk_gate.active_freeze_reasons(risk_scope):
                    raise ManagedExecutionBindingError(
                        "managed account cancellation freeze is not active"
                    )
            except ManagedExecutionBindingError:
                raise
            except Exception as error:
                raise ManagedExecutionBindingError(
                    "managed account cancellation UNKNOWN freeze could not be persisted"
                ) from error

    def _recover_interrupted_cancellation_dispatches(
        self, *, defer_if_writer_unavailable: bool = False
    ) -> None:
        """Fence old DISPATCHING rows before a supported adapter accepts cancels.

        Recovery runs only for a fully composed direct runtime or the exact
        offline fake replay contract. The SDK facade acquires the account
        writer lease and changes current-scope interrupted provider dispatches
        to UNKNOWN without retrying provider I/O. Runtime fakes without durable
        state keep their established projection-only path.
        """

        if not self._supports_cancellation_recovery_contract():
            return
        if getattr(self.runtime, "state_directory", None) is None:
            return

        scope = getattr(self.runtime, "scope", None)
        if scope is None:
            raise ManagedExecutionBindingError(
                "managed runtime lacks interrupted cancellation scope"
            )
        facade = self._get_cancellation_facade()
        if getattr(facade, "scope", None) != scope:
            raise ManagedExecutionBindingError(
                "managed cancellation recovery facade has a foreign execution scope"
            )
        recover = getattr(facade, "recover_interrupted_dispatches", None)
        if not callable(recover):
            raise ManagedExecutionBindingError(
                "managed runtime lacks interrupted cancellation recovery"
            )
        try:
            records = recover()
        except Exception as error:
            if (
                defer_if_writer_unavailable
                and getattr(error, "code", None) == "writer_lease_unavailable"
            ):
                # A different account writer may still own the lease. Keep
                # this bridge constructible for read-only recovery inspection,
                # but block every managed mutation until a later retry fences
                # interrupted dispatches under the current writer lease.
                self._interrupted_cancellation_recovery_pending = True
                return
            raise ManagedExecutionBindingError(
                "managed interrupted cancellation recovery failed"
            ) from error
        if not isinstance(records, tuple):
            raise ManagedExecutionBindingError(
                "managed interrupted cancellation recovery returned an invalid result"
            )
        for record in records:
            state = getattr(getattr(record, "state", None), "value", None)
            cancel_id = getattr(record, "cancel_id", None)
            if (
                getattr(record, "scope_key", None) != getattr(scope, "key", None)
                or state != "UNKNOWN"
                or not isinstance(cancel_id, str)
                or not cancel_id
            ):
                raise ManagedExecutionBindingError(
                    "managed interrupted cancellation recovery returned foreign evidence"
                )
        self._interrupted_cancellation_recovery_pending = False

    def _ensure_interrupted_cancellation_recovery(self) -> None:
        """Retry deferred startup recovery before any managed state mutation."""

        if not self._interrupted_cancellation_recovery_pending:
            return
        self._recover_interrupted_cancellation_dispatches()
        self._recover_unknown_cancellation_freezes()

    def _freeze_unknown_cancellation(self, record: Any) -> None:
        """Persist an account freeze when a cancellation outcome is uncertain."""

        cancel_id = getattr(record, "cancel_id", None)
        if not isinstance(cancel_id, str) or not cancel_id:
            raise ManagedExecutionBindingError("unknown cancellation record lacks cancel identity")
        risk_gate = getattr(self.runtime, "risk_gate", None)
        risk_scope = getattr(self.runtime, "risk_scope", None)
        freeze = getattr(risk_gate, "freeze", None)
        if risk_scope is None or not callable(freeze):
            raise ManagedExecutionBindingError("managed runtime lacks cancellation freeze controls")
        cause_id = self._cancel_unknown_freeze_cause(cancel_id)
        try:
            freeze(risk_scope, cause_id, cause_id)
        except Exception as error:
            raise ManagedExecutionBindingError(
                "managed cancellation unknown freeze could not be persisted"
            ) from error

    def _cancellation_admission_risk_intent_id(self, intent: Any) -> str:
        """Derive the local account-reservation id without changing cancel identity."""

        scope_key = getattr(getattr(intent, "scope", None), "key", None)
        cancel_id = getattr(intent, "cancel_id", None)
        if not isinstance(scope_key, str) or not scope_key:
            raise ManagedExecutionBindingError(
                "managed cancellation admission lacks execution scope"
            )
        if not isinstance(cancel_id, str) or not cancel_id:
            raise ManagedExecutionBindingError(
                "managed cancellation admission lacks cancellation identity"
            )
        return "cancel-admission:" + scope_key + ":" + cancel_id

    def _cancel_unknown_freeze_cause(self, cancel_id: str) -> str:
        scope_key = getattr(getattr(self.runtime, "scope", None), "key", None)
        if not isinstance(scope_key, str) or not scope_key:
            raise ManagedExecutionBindingError("managed cancellation freeze lacks execution scope")
        if not isinstance(cancel_id, str) or not cancel_id:
            raise ManagedExecutionBindingError(
                "managed cancellation freeze lacks cancellation identity"
            )
        return "cancel-outcome-unknown:" + scope_key + ":" + cancel_id


def bind_managed_execution(
    store: Any, effective: EffectiveRuntimeConfig, runtime: Any
) -> ManagedExecutionBridge:
    """Attach a bridge only for a trusted resolved managed runtime contract."""

    if getattr(effective, "profile", None) is not None or getattr(
        getattr(effective, "registration", None), "profiles", ()
    ):
        raise ManagedExecutionBindingError(
            "profile_dispatch_unavailable: profile-scoped managed execution dispatch is not enabled"
        )
    if effective.order_route != "managed_execution" or not effective.required_capabilities:
        raise ManagedExecutionBindingError(
            "effective configuration is not a managed execution route"
        )
    # A scope comparison alone is insufficient: a process could compose a
    # different managed preset, then attach its direct Store port to this
    # configuration.  The SDK composition root retains the exact sealed
    # capability contract.  Compare its complete security-relevant shape here
    # without importing the optional SDK package into normal Backtrader loads.
    #
    contract = getattr(runtime, "contract", None)
    if contract is None:
        raise ManagedExecutionBindingError("managed runtime has no sealed capability contract")
    expected_contract = {
        "strategy_id": effective.strategy_id,
        "mode": effective.mode,
        "preset": effective.preset,
        "environment": getattr(getattr(effective, "policy", None), "environment", None),
        "order_route": effective.order_route,
        "effective_digest": effective.effective_digest,
    }
    for name, expected_value in expected_contract.items():
        if expected_value is None or getattr(contract, name, None) != expected_value:
            raise ManagedExecutionBindingError(
                "managed runtime contract does not match effective configuration: " + name
            )
    if getattr(store, "_sdk_mode", False):
        store_execution_config = getattr(store, "_sdk_execution_config", None)
        store_strategy_id = (
            store_execution_config.get("strategy_id")
            if isinstance(store_execution_config, Mapping)
            else None
        )
        if store_strategy_id != effective.strategy_id:
            raise ManagedExecutionBindingError(
                "managed runtime strategy scope does not match SDK Store execution config"
            )
    expected_capabilities = tuple(effective.required_capabilities)
    runtime_capabilities = getattr(contract, "required_capabilities", None)
    if not isinstance(runtime_capabilities, tuple) or runtime_capabilities != expected_capabilities:
        raise ManagedExecutionBindingError(
            "managed runtime contract does not match effective configuration: required_capabilities"
        )
    scope = getattr(runtime, "scope", None)
    if scope is None:
        raise ManagedExecutionBindingError("managed runtime has no execution scope")
    if getattr(scope, "strategy_id", None) != effective.strategy_id:
        raise ManagedExecutionBindingError(
            "managed runtime strategy scope does not match configuration"
        )
    expected_environment = getattr(getattr(effective, "policy", None), "environment", None)
    if expected_environment is None or getattr(scope, "environment", None) != expected_environment:
        raise ManagedExecutionBindingError(
            "managed runtime environment scope does not match configuration"
        )
    if getattr(effective, "preset", None) == "managed_live_gateway":
        # The gateway client implements the same small ``submit`` port as the
        # direct managed runtime, but it must prove that the Store callback is
        # intentionally discarded and that dispatch is delegated to the typed
        # gateway transport.  Merely supplying a gateway-shaped contract would
        # otherwise re-open the legacy direct provider path below.
        if getattr(runtime, "gateway_dispatch", None) != "zmq_gateway_v1":
            raise ManagedExecutionBindingError(
                "managed gateway runtime lacks the sealed ZMQ dispatch adapter"
            )

    is_ctp_store = getattr(store, "_is_ctp_session_provider", None)
    try:
        ctp_store = callable(is_ctp_store) and is_ctp_store() is True
    except Exception as error:
        raise ManagedExecutionBindingError(
            "managed Store CTP route could not be validated"
        ) from error
    if ctp_store:
        if str(getattr(scope, "provider", "")).strip().upper() != "CTP":
            raise ManagedExecutionBindingError(
                "managed runtime provider scope does not match the CTP Store"
            )
        # Do not hand a CTP Store the generic synchronous legacy callback.
        # The SDK path is asynchronous and this repository has no
        # write-authorizing CTP admission with a compatible observation
        # handoff yet. The typed adapter refuses before calling its SDK port;
        # replacing it requires a reviewed implementation of both contracts.
        bridge = CtpManagedExecutionAdapterPlaceholder(runtime=runtime)
    else:
        bridge = ManagedExecutionBridge(runtime=runtime)
    attach = getattr(store, "attach_managed_execution_adapter", None)
    if not callable(attach):
        raise ManagedExecutionBindingError("Store cannot attach a managed execution adapter")
    attach(bridge)
    return bridge
