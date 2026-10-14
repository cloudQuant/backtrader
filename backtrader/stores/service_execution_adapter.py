"""Managed execution adapter backed by the SDK service execution client.

``BtApiStore`` accepts one deliberate ``managed_execution_adapter`` port.  This
adapter fills that port with the authenticated execution service: the store
keeps its order projection and the service keeps the durable intent, admission
and provider dispatch.  The adapter is a borrowed facade over an injected SDK
client; it never starts a thread, never registers, and never calls the private
legacy dispatcher, because a missing journal, permit or provider fact must not
become an accidental direct write.

Managed order identity is read from the framework metadata the broker already
publishes (``managed_intent_id``, ``managed_signal_id``, ``managed_instrument``,
``managed_position_effect``, ``managed_metadata_version``).  A response is
always one of three shapes the broker already understands: an accepted
projection carrying the provider order identity, a nonterminal unknown
projection, or a structured rejection.  The adapter therefore raises no
transport error into the strategy: an uncertain outcome must stay visible as an
unreconciled order rather than as a failed call the strategy might retry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from backtrader.stores.managed_execution import ManagedExecutionAdapterError

#: Codes that prove the service refused the request without touching the
#: provider.  Only these may become a local rejection: an unrecognized code is
#: not evidence that the provider saw nothing, so everything else stays a
#: nonterminal unknown projection that must be reconciled.
_DEFINITIVE_REJECTION_CODES = frozenset(
    {
        "ADMISSION_REQUIRED",
        "CAPACITY",
        "CANCEL_TARGET_UNKNOWN",
        "CAPABILITY_UNAVAILABLE",
        "CLOSED",
        "CONFLICT",
        "DENIED",
        "DUPLICATE_ACTIVE_RUN",
        "INVALID_REPLY",
        "INVALID_REQUEST",
        "INTENT_CONFLICT",
        "NOT_REGISTERED",
        "OWNER_LEASE_UNAVAILABLE",
        "POLICY_REQUIREMENT_UNMET",
        "QUERY_NOT_CONFIGURED",
        "RECORD_MISSING",
        "REQUEST_NOT_SENT",
        "ROLE_NOT_AUTHORIZED",
        "SCOPE_DENIED",
        "STALE_EPOCH",
        "STATE_CONFLICT",
        "STORE_UNAVAILABLE",
        "UNSUPPORTED_OPERATION",
    }
)

#: Durable states whose provider order identity is confirmed.
_ACCEPTED_STATES = frozenset({"ACKED", "PARTIALLY_FILLED", "FILLED"})

#: Durable states that end the framework order locally.
_REJECTED_STATES = frozenset({"REJECTED", "BLOCKED"})

_DEFAULT_METADATA_VERSION = "backtrader.service-execution.v1"


class ServiceExecutionAdapterError(ManagedExecutionAdapterError):
    """Finite local diagnostics for an unusable service execution adapter."""


class ServiceExecutionAdapter:
    """Project framework orders onto one authenticated execution service."""

    #: The service owns provider dispatch; the store must not treat this
    #: adapter as a local provider fill projection.
    managed_provider_projection_enabled = False

    def __init__(
        self,
        client: Any,
        *,
        metadata_version: str = _DEFAULT_METADATA_VERSION,
        order_ref_factory: Optional[Callable[[Any], str]] = None,
    ) -> None:
        if not callable(getattr(client, "submit", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires submit")
        if not callable(getattr(client, "cancel", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires cancel")
        if type(metadata_version) is not str or not metadata_version.strip():
            raise ServiceExecutionAdapterError("invalid metadata_version")
        if order_ref_factory is not None and not callable(order_ref_factory):
            raise ServiceExecutionAdapterError("invalid order_ref_factory")

        self._client = client
        self._metadata_version = metadata_version
        self._order_ref_factory = order_ref_factory

    # -- submission ---------------------------------------------------------

    def submit_order(self, order: Any, legacy_dispatch: Any) -> Mapping[str, Any]:
        """Submit one framework order through the execution service.

        ``legacy_dispatch`` is accepted only to satisfy the Store port.  It is
        never invoked: routing a service-managed order through the legacy
        provider path would bypass the durable intent and its admission.
        """

        del legacy_dispatch
        identity = _managed_identity(order, self._metadata_version)
        if identity is None:
            return _rejection(
                "managed_order_metadata_missing",
                "Managed order metadata is incomplete; the intent was not routed.",
                order=order,
            )
        content = _order_content(order)
        if content is None:
            return _rejection(
                "managed_order_content_unsupported",
                "Order type or size cannot be expressed as a managed intent.",
                order=order,
                intent_id=identity["intent_id"],
            )

        try:
            view = self._client.submit(
                intent_id=identity["intent_id"],
                signal_id=identity["signal_id"],
                instrument=identity["instrument"],
                side=content["side"],
                position_effect=identity["position_effect"],
                order_type=content["order_type"],
                quantity=content["quantity"],
                price=content["price"],
                reduce_only=identity["reduce_only"],
                metadata_version=identity["metadata_version"],
                tags=_tags(order, self._order_ref_factory),
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite projection
            return _failure_projection(error, order=order, intent_id=identity["intent_id"])
        return _submission_projection(view, order)

    # -- cancellation -------------------------------------------------------

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        legacy_dispatch: Any,
    ) -> Mapping[str, Any]:
        """Cancel one order whose provider identity the journal evidenced."""

        del legacy_dispatch
        info = _order_info(order_or_ref)
        target_intent_id = info.get("managed_intent_id")
        if not _reference(target_intent_id):
            return _rejection(
                "managed_cancel_metadata_missing",
                "Cancellation requires the managed intent identifier.",
                data_name=dataname,
            )
        # One durable identity per cancellation attempt.  An explicit
        # identifier wins; otherwise the framework convention derives a stable
        # one from the intent, so re-cancelling the same intent is idempotent
        # instead of creating a second cancellation record.
        declared_cancel_id = info.get("managed_cancel_intent_id")
        cancel_id = (
            declared_cancel_id if _reference(declared_cancel_id) else f"cancel.{target_intent_id}"
        )
        provider_order_id = info.get("external_order_id")
        if not _reference(provider_order_id):
            return _rejection(
                "managed_cancel_provider_identity_missing",
                "Cancellation requires the provider order identity confirmed by the service.",
                data_name=dataname,
                intent_id=target_intent_id,
            )

        try:
            view = self._client.cancel(
                cancel_id=cancel_id,
                target_intent_id=target_intent_id,
                provider_order_id=provider_order_id,
                metadata_version=_metadata_version_of(info, self._metadata_version),
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite projection
            return _cancel_failure_projection(error, data_name=dataname, cancel_id=cancel_id)
        return _cancellation_projection(view, dataname)


# -- identity and content ---------------------------------------------------


def _managed_identity(order: Any, default_metadata_version: str) -> Optional[dict[str, Any]]:
    info = _order_info(order)
    intent_id = info.get("managed_intent_id")
    signal_id = info.get("managed_signal_id")
    instrument = info.get("managed_instrument")
    position_effect = info.get("managed_position_effect")
    if not (_reference(intent_id) and _reference(signal_id)):
        return None
    if not (_instrument(instrument) and position_effect in _POSITION_EFFECTS):
        return None
    return {
        "intent_id": intent_id,
        "signal_id": signal_id,
        "instrument": instrument,
        "position_effect": position_effect,
        "reduce_only": bool(info.get("reduce_only", False)) or position_effect != "OPEN",
        "metadata_version": _metadata_version_of(info, default_metadata_version),
    }


def _order_content(order: Any) -> Optional[dict[str, Any]]:
    exectype = getattr(order, "exectype", None)
    created = getattr(order, "created", None)
    raw_size = getattr(created, "size", None)
    if raw_size is None:
        raw_size = getattr(order, "size", None)
    try:
        size = Decimal(str(raw_size))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not size.is_finite() or size == 0:
        return None
    quantity = abs(size)
    side = "BUY" if _is_buy(order, size) else "SELL"

    limit, market = _execution_types()
    if exectype == limit:
        raw_price = getattr(created, "price", None)
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite() or price <= 0:
            return None
        return {
            "side": side,
            "order_type": "LIMIT",
            "quantity": quantity,
            "price": price,
        }
    if exectype == market:
        return {"side": side, "order_type": "MARKET", "quantity": quantity, "price": None}
    # Stop, stop-limit, trailing and bracket orders are not silently downgraded.
    return None


def _execution_types() -> tuple[Any, Any]:
    from backtrader.order import Order

    return Order.Limit, Order.Market


def _is_buy(order: Any, size: Decimal) -> bool:
    isbuy = getattr(order, "isbuy", None)
    if callable(isbuy):
        return bool(isbuy())
    return size > 0


def _tags(order: Any, order_ref_factory: Optional[Callable[[Any], str]]) -> dict[str, str]:
    """Return the stable tags for one intent.

    The framework order reference is deliberately *not* sent by default: it is
    a per-object counter, so including it would make the same logical intent
    look like different content and the service would refuse it as a conflict
    instead of returning the durable record.  A deployment that has its own
    stable reference scheme may inject ``order_ref_factory`` to publish it.
    """

    if order_ref_factory is None:
        return {}
    candidate = order_ref_factory(order)
    return {"framework_order_ref": candidate} if _reference(candidate) else {}


# -- projections ------------------------------------------------------------


def _submission_projection(view: Any, order: Any) -> Mapping[str, Any]:
    state = _state_of(view)
    projection = {
        "kind": "service_execution_record",
        "managed_intent_id": _view_text(view, "intent_id"),
        "service_execution_state": state,
        "service_dispatch_attempts": getattr(view, "dispatch_attempts", None),
        "data_name": _data_name(order),
    }
    if state in _ACCEPTED_STATES:
        provider_order_id = _view_text(view, "provider_order_id")
        if provider_order_id is not None:
            projection["external_order_id"] = provider_order_id
        projection["status"] = "accepted"
        return projection
    if state == "UNKNOWN":
        projection.update(
            {
                "status": "pending",
                "execution_unknown": True,
                "error_code": "service_execution_outcome_unknown",
                "error_msg": (
                    "The execution service could not prove the provider outcome; "
                    "reconcile the original intent before resubmitting."
                ),
            }
        )
        return projection
    projection.update(
        {
            "status": "rejected",
            "error_code": f"service_execution_{state.lower()}",
            "error_msg": f"Execution service recorded state {state} for this intent.",
        }
    )
    return projection


def _cancellation_projection(view: Any, dataname: Optional[str]) -> Mapping[str, Any]:
    state = _state_of(view)
    projection = {
        "kind": "service_execution_record",
        "managed_cancel_intent_id": _view_text(view, "cancel_id"),
        "managed_intent_id": _view_text(view, "target_intent_id"),
        "service_execution_cancel_state": state,
        "data_name": dataname,
    }
    provider_order_id = _view_text(view, "provider_order_id")
    if provider_order_id is not None:
        projection["external_order_id"] = provider_order_id
    if state == "ACKED":
        # An acknowledged cancellation is not a terminal framework state: a
        # late fill or a separately reconciled terminal update may still arrive.
        projection.update(
            {
                "status": "cancel_requested",
                "managed_execution_cancel_pending": True,
                "managed_execution_cancel_reconciliation_required": True,
            }
        )
        return projection
    if state == "CANCELLED":
        projection["status"] = "cancelled"
        return projection
    if state == "UNKNOWN":
        projection.update(
            {
                "status": "pending",
                "execution_unknown": True,
                "managed_execution_cancel_pending": True,
                "managed_execution_cancel_reconciliation_required": True,
                "error_code": "service_execution_cancel_outcome_unknown",
                "error_msg": (
                    "The execution service could not prove the cancellation outcome; "
                    "reconcile the original cancellation before retrying."
                ),
            }
        )
        return projection
    projection.update(
        {
            "status": "rejected",
            "error_code": f"service_execution_cancel_{state.lower()}",
            "error_msg": f"Execution service recorded cancellation state {state}.",
        }
    )
    return projection


def _failure_projection(error: BaseException, *, order: Any, intent_id: str) -> Mapping[str, Any]:
    code = _error_code(error)
    if code not in _DEFINITIVE_REJECTION_CODES:
        return {
            "kind": "service_execution_record",
            "managed_intent_id": intent_id,
            "service_execution_state": "UNKNOWN",
            "status": "pending",
            "execution_unknown": True,
            "error_code": code,
            "error_msg": (
                "The execution request outcome is unknown; reconcile the original "
                "intent instead of resubmitting it."
            ),
            "data_name": _data_name(order),
        }
    return _rejection(
        code,
        "The execution service did not accept the intent.",
        order=order,
        intent_id=intent_id,
    )


def _cancel_failure_projection(
    error: BaseException, *, data_name: Optional[str], cancel_id: str
) -> Mapping[str, Any]:
    code = _error_code(error)
    if code not in _DEFINITIVE_REJECTION_CODES:
        return {
            "kind": "service_execution_record",
            "managed_cancel_intent_id": cancel_id,
            "service_execution_cancel_state": "UNKNOWN",
            "status": "pending",
            "execution_unknown": True,
            "managed_execution_cancel_pending": True,
            "managed_execution_cancel_reconciliation_required": True,
            "error_code": code,
            "error_msg": "The cancellation outcome is unknown; reconcile before retrying.",
            "data_name": data_name,
        }
    return _rejection(
        code,
        "The execution service did not accept the cancellation.",
        data_name=data_name,
    )


def _rejection(
    code: str,
    message: str,
    *,
    order: Any = None,
    data_name: Optional[str] = None,
    intent_id: Optional[str] = None,
) -> Mapping[str, Any]:
    projection: dict[str, Any] = {
        "status": "rejected",
        "error_code": code,
        "error_msg": message,
    }
    if order is not None:
        projection["data_name"] = _data_name(order)
    elif data_name is not None:
        projection["data_name"] = data_name
    if intent_id is not None:
        projection["managed_intent_id"] = intent_id
    return projection


# -- small helpers ----------------------------------------------------------


def _order_info(order: Any) -> Mapping[str, Any]:
    info = getattr(order, "info", None)
    if isinstance(info, Mapping):
        return info
    getter = getattr(info, "get", None)
    if callable(getter):
        return {key: getter(key) for key in _MANAGED_INFO_KEYS}
    return {}


_MANAGED_INFO_KEYS = (
    "managed_intent_id",
    "managed_signal_id",
    "managed_instrument",
    "managed_position_effect",
    "managed_metadata_version",
    "managed_cancel_intent_id",
    "external_order_id",
    "reduce_only",
)


def _metadata_version_of(info: Mapping[str, Any], default: str) -> str:
    value = info.get("managed_metadata_version")
    return value if _reference(value) else default


def _data_name(order: Any) -> Optional[str]:
    data = getattr(order, "data", None)
    for attribute in ("_name", "dataname", "name"):
        value = getattr(data, attribute, None)
        if isinstance(value, str) and value:
            return value
    return None


def _state_of(view: Any) -> str:
    state = getattr(view, "state", None)
    return state if isinstance(state, str) else "UNKNOWN"


def _view_text(view: Any, attribute: str) -> Optional[str]:
    value = getattr(view, attribute, None)
    return value if _reference(value) else None


def _error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code and code.isascii():
        return code
    return "service_execution_request_failed"


_POSITION_EFFECTS = frozenset({"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"})


def _reference(value: Any) -> bool:
    if type(value) is not str or not value or len(value) > 128:
        return False
    if value != value.strip():
        return False
    return all(character.isalnum() or character in "._:-" for character in value)


def _instrument(value: Any) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 192:
        return False
    if not value[0].isascii() or not value[0].isalnum():
        return False
    return all(
        character.isascii() and (character.isalnum() or character in "._:/-") for character in value
    )


__all__ = [
    "ServiceExecutionAdapter",
    "ServiceExecutionAdapterError",
]
