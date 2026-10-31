"""Backtrader-owned CTP managed-order and queue-receipt contracts.

This module was extracted from the retired ``backtrader_runtime`` projection
package.  It owns only the framework-side mapping and validation that the
Store adapter needs: canonical order facts, strict limit-intent construction,
the stable runtime order identity, and local queue-receipt classification.
It performs no provider I/O and imports no SDK, plugin, or runtime package.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional


__all__ = [
    "CtpQueueReceiptClassification",
    "CtpQueueReceiptState",
    "ManagedExecutionBindingError",
    "classify_ctp_queue_receipt",
    "strict_limit_intent_from_order",
]

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
