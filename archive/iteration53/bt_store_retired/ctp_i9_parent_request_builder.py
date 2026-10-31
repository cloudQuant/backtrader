"""Unregistered source contract for echoing an I9 CTP action as parent DTOs.

This module stages only in the exact I9 SQLite execution store and mirrors
the already-owned OrderRef into the parent execution journal. It never queues,
claims, sends, or returns a dispatch capability. The normalized request is a
lossy view by design: the complete canonical native payload (including
``CombHedgeFlag``), approval echo, session binding, and I9 row binding remain
in the returned contract. The ordinary Store enqueue path does not call this
module and managed dispatch remains closed.

The cancel builder requires a fresh handle issued by the same I9 store after
an injected target verifier succeeds. The default I9 target verifier rejects;
no production query verifier is supplied here. A successful fake-only call is
not provider provenance, account-wide writer exclusion, or write authority.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, fields, replace
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from typing import Any, Literal, Mapping, Optional, Tuple

from .ctp_i9_managed_dispatch import (
    CtpI9ManagedDispatchBridge,
    _assert_command_row_matches,
    _binding_from_i9,
    _require_binding_matches_prepared,
    _trusted_i9_types,
)


_SUBMIT_REQUIRED = frozenset(
    {
        "InstrumentID",
        "OrderRef",
        "Direction",
        "CombOffsetFlag",
        "CombHedgeFlag",
        "OrderPriceType",
        "LimitPrice",
        "VolumeTotalOriginal",
        "TimeCondition",
        "ExchangeID",
    }
)
_SUBMIT_OPTIONAL = frozenset(
    {
        "BrokerID",
        "InvestorID",
        "UserID",
        "GTDDate",
        "VolumeCondition",
        "MinVolume",
        "ContingentCondition",
        "StopPrice",
        "ForceCloseReason",
        "IsAutoSuspend",
        "UserForceClose",
        "IsSwapOrder",
        "BusinessUnit",
        "InvestUnitID",
        "AccountID",
        "RequestID",
    }
)
_CANCEL_REQUIRED = frozenset(
    {
        "InstrumentID",
        "OrderRef",
        "ExchangeID",
        "OrderSysID",
        "FrontID",
        "SessionID",
        "ActionFlag",
        "LimitPrice",
        "VolumeChange",
    }
)
_CANCEL_OPTIONAL = frozenset(
    {"BrokerID", "InvestorID", "UserID", "InvestUnitID", "AccountID", "RequestID"}
)


class CtpI9ParentRequestBuilderError(ValueError):
    """Redacted failure for the optional, non-dispatch request builder."""


@dataclass(frozen=True)
class CtpI9ParentRequestContract:
    """Prepared I9 row, parent DTO, and complete immutable payload echo.

    ``prepared_dispatch`` and ``i9_dispatch_binding`` are correlation values;
    neither is an executor handle. Consumers must not infer that this contract
    permits an ordinary Store queue, SDK call, or provider write.
    """

    operation: Literal["submit", "cancel"]
    prepared_dispatch: Any
    i9_dispatch_binding: Any
    parent_request: Any
    canonical_request_payload_json: str
    request_payload_sha256: str
    parent_reservation_mirror: Any

    @property
    def dispatch_authorized(self) -> bool:
        """The DTO/readback contract never authorizes dispatch."""

        return False


def _parent_types() -> Tuple[type, ...]:
    if sys.version_info < (3, 11):
        raise CtpI9ParentRequestBuilderError("supported parent candidate runtime is unavailable")
    try:
        if version("bt_api_py") != "0.15.5":
            raise ValueError("unsupported bt_api_py version")
        from bt_api_py.bt_api import BtApi
        from bt_api_py._contracts.models import (
            CancelOrderRequest,
            CtpCancelIdentityBinding,
            CtpOrderIdentityBinding,
            OrderRequest,
            OrderType,
            Side,
        )
        from bt_api_py._execution_session import CtpOrderIdentityReservationMirror
    except Exception as error:
        raise CtpI9ParentRequestBuilderError(
            "trusted parent request DTO candidate is unavailable"
        ) from error
    return (
        BtApi,
        OrderRequest,
        CancelOrderRequest,
        CtpOrderIdentityBinding,
        CtpCancelIdentityBinding,
        CtpOrderIdentityReservationMirror,
        OrderType,
        Side,
    )


def _i9_types() -> Tuple[type, ...]:
    if sys.version_info < (3, 11):
        raise CtpI9ParentRequestBuilderError("supported I9 candidate runtime is unavailable")
    try:
        if version("bt_api_execution") != "0.2.0":
            raise ValueError("unsupported bt_api_execution version")
        types = _trusted_i9_types()
        if types is None or len(types) != 8:
            raise ValueError("reviewed I9 same-store types are unavailable")
        return types
    except Exception as error:
        raise CtpI9ParentRequestBuilderError(
            "trusted I9 same-store candidate is unavailable"
        ) from error


def _snapshot_mapping(value: Any, label: str, canonical_json: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise CtpI9ParentRequestBuilderError(label + " must be a mapping")
    try:
        detached = json.loads(canonical_json(dict(value)))
    except Exception as error:
        raise CtpI9ParentRequestBuilderError(label + " is not canonical JSON") from error
    if type(detached) is not dict or any(type(key) is not str for key in detached):
        raise CtpI9ParentRequestBuilderError(label + " has invalid fields")
    return detached, canonical_json(detached)


def _typed_equal(left: Any, right: Any) -> bool:
    """Compare payload facts without Python's bool/int equivalence."""

    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        return left.keys() == right.keys() and all(
            _typed_equal(left[key], right[key]) for key in left
        )
    if type(left) in (list, tuple) or type(right) in (list, tuple):
        if type(left) is not type(right) or len(left) != len(right):
            return False
        return all(
            _typed_equal(left_item, right_item) for left_item, right_item in zip(left, right)
        )
    if type(left) is not type(right):
        return False
    if getattr(type(left), "__dataclass_fields__", None) is not None:
        return _typed_dataclass_equal(left, right)
    return left == right


def _typed_dataclass_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    try:
        return all(
            _typed_equal(getattr(left, field.name), getattr(right, field.name))
            for field in fields(left)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isascii()
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
    return value


def _finite_decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is bool or type(value) not in (int, float, str, Decimal):
        raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
    if type(value) is float and not math.isfinite(value):
        raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
    try:
        result = value if type(value) is Decimal else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name) from error
    if not result.is_finite() or (positive and result <= 0):
        raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
    return result


def _validate_optional_scalar_fields(
    payload: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    numeric: frozenset[str],
    integer: frozenset[str],
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise CtpI9ParentRequestBuilderError("native request schema has unsupported fields")
    for name in set(payload) & (allowed - numeric - integer):
        value = payload[name]
        if type(value) is not str or not value.isascii() or value != value.strip():
            raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
    for name in set(payload) & numeric:
        value = payload[name]
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)
        _finite_decimal(value, name)
    for name in set(payload) & integer:
        value = payload[name]
        if type(value) is not int or value < 0:
            raise CtpI9ParentRequestBuilderError("native request schema has invalid " + name)


def _submit_parent_fields(payload: Mapping[str, Any], scope: Any, parent: Tuple[type, ...]):
    if not set(payload) >= _SUBMIT_REQUIRED or set(payload) - (_SUBMIT_REQUIRED | _SUBMIT_OPTIONAL):
        raise CtpI9ParentRequestBuilderError(
            "native submit request schema is incomplete or unsupported"
        )
    _validate_optional_scalar_fields(
        payload,
        _SUBMIT_REQUIRED | _SUBMIT_OPTIONAL,
        numeric=frozenset({"LimitPrice", "StopPrice"}),
        integer=frozenset(
            {
                "VolumeTotalOriginal",
                "MinVolume",
                "IsAutoSuspend",
                "UserForceClose",
                "IsSwapOrder",
                "RequestID",
            }
        ),
    )
    instrument = _required_text(payload, "InstrumentID")
    exchange = _required_text(payload, "ExchangeID")
    order_ref = _required_text(payload, "OrderRef")
    if not re.fullmatch(r"[0-9]{12}", order_ref, re.ASCII):
        raise CtpI9ParentRequestBuilderError("native submit request OrderRef is invalid")
    direction = _required_text(payload, "Direction")
    side_value = {"0": "buy", "1": "sell"}.get(direction)
    offset_value = {
        "0": "open",
        "1": "close",
        "3": "close_today",
        "4": "close_yesterday",
    }.get(_required_text(payload, "CombOffsetFlag"))
    hedge_flag = _required_text(payload, "CombHedgeFlag")
    if hedge_flag not in {"1", "2", "3"}:
        raise CtpI9ParentRequestBuilderError("native submit request hedge flag is invalid")
    if side_value is None or offset_value is None:
        raise CtpI9ParentRequestBuilderError("native submit direction or offset is unsupported")
    price_type = _required_text(payload, "OrderPriceType")
    time_condition = _required_text(payload, "TimeCondition")
    time_in_force = {"1": "IOC", "3": "GTC"}.get(time_condition)
    if time_in_force is None:
        raise CtpI9ParentRequestBuilderError("native submit time condition is unsupported")
    quantity = payload.get("VolumeTotalOriginal")
    if type(quantity) is not int or quantity <= 0:
        raise CtpI9ParentRequestBuilderError("native submit quantity is invalid")
    price_value = _finite_decimal(payload.get("LimitPrice"), "LimitPrice")
    if price_type == "2":
        order_type = parent[6].LIMIT
        price: Optional[Decimal] = _finite_decimal(price_value, "LimitPrice", positive=True)
    elif price_type == "1":
        order_type = parent[6].MARKET
        if price_value != 0:
            raise CtpI9ParentRequestBuilderError(
                "market submit must carry a zero native limit price"
            )
        price = None
    else:
        raise CtpI9ParentRequestBuilderError("native submit price type is unsupported")
    native_request_id = payload.get("RequestID")
    if native_request_id is not None and (
        type(native_request_id) is not int or native_request_id <= 0
    ):
        raise CtpI9ParentRequestBuilderError("native submit RequestID is invalid")
    account_id = getattr(scope, "account_ref", None)
    if type(account_id) is not str or not account_id or account_id != account_id.strip():
        raise CtpI9ParentRequestBuilderError("I9 CTP scope account reference is invalid")
    return {
        "symbol": instrument,
        "account_id": account_id,
        "client_order_id": order_ref,
        "side": parent[7](side_value),
        "order_type": order_type,
        "quantity": Decimal(quantity),
        "price": price,
        "time_in_force": time_in_force,
        "reduce_only": offset_value != "open",
        "quantity_unit": "contracts",
        "offset": offset_value,
        "exchange_id": exchange,
    }


def _validate_cancel_payload(
    payload: Mapping[str, Any], prepared: Any
) -> tuple[str, str, str, str, int, int]:
    if "OrderActionRef" in payload or getattr(prepared, "native_action_ref", None) is not None:
        raise CtpI9ParentRequestBuilderError(
            "caller-supplied native ActionRef is forbidden before Store staging"
        )
    if not set(payload) >= _CANCEL_REQUIRED or set(payload) - (_CANCEL_REQUIRED | _CANCEL_OPTIONAL):
        raise CtpI9ParentRequestBuilderError(
            "native cancel request schema is incomplete or unsupported"
        )
    _validate_optional_scalar_fields(
        payload,
        _CANCEL_REQUIRED | _CANCEL_OPTIONAL,
        numeric=frozenset({"LimitPrice"}),
        integer=frozenset({"FrontID", "SessionID", "VolumeChange", "RequestID"}),
    )
    instrument = _required_text(payload, "InstrumentID")
    order_ref = _required_text(payload, "OrderRef")
    exchange = _required_text(payload, "ExchangeID")
    order_sys_id = _required_text(payload, "OrderSysID")
    front_id = payload.get("FrontID")
    session_id = payload.get("SessionID")
    action_flag = _required_text(payload, "ActionFlag")
    if (
        not re.fullmatch(r"[0-9]{12}", order_ref, re.ASCII)
        or type(front_id) is not int
        or front_id <= 0
        or type(session_id) is not int
        or session_id <= 0
        or order_ref != prepared.order_ref
        or exchange != prepared.cancel_target_exchange_id
        or order_sys_id != prepared.cancel_target_order_sys_id
        or front_id != prepared.cancel_target_front_id
        or session_id != prepared.cancel_target_session_id
        or action_flag != "0"
        or _finite_decimal(payload.get("LimitPrice"), "LimitPrice") != 0
        or payload.get("VolumeChange") != 0
        or type(payload.get("VolumeChange")) is not int
        or ("RequestID" in payload and payload["RequestID"] != prepared.native_request_id)
    ):
        raise CtpI9ParentRequestBuilderError("native cancel request identity is inconsistent")
    return instrument, order_ref, exchange, order_sys_id, front_id, session_id


class CtpI9ParentRequestBuilder:
    """Explicit source-only same-I9-store builder with no queue/send methods."""

    def __init__(self, *, bridge: CtpI9ManagedDispatchBridge, parent_api: Any, exchange_name: str):
        if type(bridge) is not CtpI9ManagedDispatchBridge:
            raise CtpI9ParentRequestBuilderError("exact I9 Store bridge is required")
        if type(exchange_name) is not str or not exchange_name or not exchange_name.isascii():
            raise CtpI9ParentRequestBuilderError("exact CTP exchange name is required")
        self._bridge = bridge
        self._parent_api = parent_api
        self._exchange_name = exchange_name

    def _contracts(self):
        parent = _parent_types()
        i9 = _i9_types()
        if type(self._parent_api) is not parent[0]:
            raise CtpI9ParentRequestBuilderError("exact parent BtApi candidate is required")
        try:
            bound_i9_types = self._bridge._require_same_store_authority()
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "exact I9 same-store binding is unavailable"
            ) from error
        if bound_i9_types != i9:
            raise CtpI9ParentRequestBuilderError("I9 bridge types differ from reviewed candidate")
        return parent, i9

    def _snapshot(self, prepared: Any, canonical_facts: Any, operation: str):
        parent, i9 = self._contracts()
        if type(prepared) is not i9[4] or prepared.operation != operation:
            raise CtpI9ParentRequestBuilderError("typed matching I9 prepared dispatch is required")
        from bt_api_execution.contracts import canonical_json, payload_sha256

        payload, payload_json = _snapshot_mapping(
            prepared.request_payload, "prepared request payload", canonical_json
        )
        if not isinstance(canonical_facts, Mapping) or not _typed_equal(
            dict(prepared.request_payload), dict(canonical_facts)
        ):
            raise CtpI9ParentRequestBuilderError(
                "canonical facts differ from the complete prepared request payload"
            )
        facts, facts_json = _snapshot_mapping(
            canonical_facts, "canonical request facts", canonical_json
        )
        if payload_json != facts_json or not _typed_equal(payload, facts):
            raise CtpI9ParentRequestBuilderError(
                "canonical facts differ from the complete prepared request payload"
            )
        session_binding, _session_json = _snapshot_mapping(
            prepared.session_binding, "prepared session binding", canonical_json
        )
        detached = replace(
            prepared,
            request_payload=payload,
            session_binding=session_binding,
        )
        return parent, i9, detached, payload, payload_json, payload_sha256(payload)

    def _parent_reservation_mirror(self, reservation: Any, scope: Any, parent: Tuple[type, ...]):
        account_key = getattr(scope, "account_key", None)
        scope_key = getattr(scope, "key", None)
        trading_day = getattr(scope, "trading_day", None)
        managed_intent_id = reservation.managed_intent_id
        runtime_order_id = reservation.runtime_order_id
        try:
            mirror = self._parent_api.consume_ctp_order_identity_reservation(
                self._exchange_name,
                scope=scope,
                identity_store=self._bridge._identity_port,
                managed_intent_id=managed_intent_id,
                runtime_order_id=runtime_order_id,
            )
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "parent I9 OrderRef mirror failed closed"
            ) from error
        if (
            type(mirror) is not parent[5]
            or (
                mirror.account_key,
                mirror.trading_day,
                mirror.scope_key,
                mirror.managed_intent_id,
                mirror.runtime_order_id,
                mirror.order_ref,
                mirror.created_at_ns,
            )
            != (
                account_key,
                trading_day,
                scope_key,
                reservation.managed_intent_id,
                reservation.runtime_order_id,
                reservation.order_ref,
                reservation.created_at_ns,
            )
            or type(mirror.created_at_ns) is not int
            or mirror.created_at_ns <= 0
        ):
            raise CtpI9ParentRequestBuilderError("parent OrderRef mirror differs from I9 readback")
        return mirror

    def build_submit_request(
        self, prepared: Any, *, canonical_facts: Mapping[str, Any]
    ) -> CtpI9ParentRequestContract:
        """Stage one exact submit row and echo its reservation as a parent DTO."""

        parent, i9, detached, payload, payload_json, payload_digest = self._snapshot(
            prepared, canonical_facts, "submit"
        )
        parent_fields = _submit_parent_fields(payload, self._bridge._scope, parent)
        if "RequestID" in payload and payload["RequestID"] != detached.native_request_id:
            raise CtpI9ParentRequestBuilderError(
                "native submit RequestID differs from prepared dispatch"
            )
        scope = self._bridge._scope
        reservation = self._bridge._identity_port.read_ctp_order_identity(
            scope, detached.managed_intent_id
        )
        if type(reservation) is not i9[2] or reservation != detached.order_ref_reservation:
            raise CtpI9ParentRequestBuilderError("same-store I9 reservation readback differs")
        if payload.get("OrderRef") != reservation.order_ref:
            raise CtpI9ParentRequestBuilderError(
                "canonical submit OrderRef differs from reservation"
            )
        try:
            staged = self._bridge.stage_prepared_dispatch(detached)
            from .ctp_i9_managed_dispatch import CtpI9ManagedDispatchHandle

            if (
                type(staged) is not CtpI9ManagedDispatchHandle
                or staged.prepared is not detached
                or type(staged.source_binding) is not i9[5]
            ):
                raise ValueError("I9 bridge returned an untyped staged binding")
            binding = _binding_from_i9(staged.source_binding)
            if not _typed_dataclass_equal(staged.binding, binding):
                raise ValueError("I9 bridge binding differs from source binding")
            _require_binding_matches_prepared(binding, detached, reservation, scope)
            command = self._bridge._identity_port.read_ctp_dispatch_command(
                scope, detached.command_id
            )
            current_reservation = self._bridge._identity_port.read_ctp_order_identity(
                scope, detached.managed_intent_id
            )
            if type(current_reservation) is not i9[2] or current_reservation != reservation:
                raise ValueError("I9 reservation changed during submit staging")
            if type(command) is not i9[7]:
                raise ValueError("I9 submit command readback is untyped")
            _assert_command_row_matches(command, binding)
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "I9 submit staging/readback failed closed"
            ) from error
        if (
            command is None
            or command.operation != "SUBMIT"
            or command.status != "READY"
            or command.request_payload_sha256 != payload_digest
            or not _typed_equal(dict(command.request_payload), payload)
            or command.native_request_payload_sha256 != payload_digest
            or not _typed_equal(dict(command.native_request_payload), payload)
            or binding.request_payload_sha256 != payload_digest
            or not _typed_equal(binding.request_payload, payload)
            or binding.native_request_payload_sha256 != payload_digest
            or not _typed_equal(binding.native_request_payload, payload)
        ):
            raise CtpI9ParentRequestBuilderError(
                "staged I9 submit row differs from canonical facts"
            )
        mirror = self._parent_reservation_mirror(reservation, scope, parent)
        scope_environment = getattr(scope, "environment", None)
        identity = parent[3](
            environment=scope_environment,
            account_key=reservation.account_key,
            trading_day=reservation.trading_day,
            scope_key=reservation.scope_key,
            managed_intent_id=reservation.managed_intent_id,
            runtime_order_id=reservation.runtime_order_id,
        )
        try:
            parent_request = parent[1](
                **parent_fields,
                ctp_order_identity=identity,
            )
        except Exception as error:
            raise CtpI9ParentRequestBuilderError("parent submit request schema rejected") from error
        if (
            parent_request.client_order_id != reservation.order_ref
            or parent_request.ctp_order_identity is not identity
            or parent_request.ctp_order_identity.dispatch_authorized is not False
        ):
            raise CtpI9ParentRequestBuilderError("parent submit DTO lost exact I9 identity")
        return CtpI9ParentRequestContract(
            operation="submit",
            prepared_dispatch=detached,
            i9_dispatch_binding=binding,
            parent_request=parent_request,
            canonical_request_payload_json=payload_json,
            request_payload_sha256=payload_digest,
            parent_reservation_mirror=mirror,
        )

    def build_cancel_request(
        self,
        prepared: Any,
        *,
        canonical_facts: Mapping[str, Any],
        target_handle: Any,
    ) -> CtpI9ParentRequestContract:
        """Stage a cancel echo only from a fresh exact same-store target handle."""

        parent, i9, detached, payload, payload_json, payload_digest = self._snapshot(
            prepared, canonical_facts, "cancel"
        )
        scope = self._bridge._scope
        store = self._bridge._identity_port
        worker = self._bridge._single_worker
        try:
            from bt_api_execution.store import (
                CtpCancelActionProjection,
                CtpDispatchProjection,
                CtpOrderTargetProjectionHandle,
                CtpProjectedOrderState,
                CtpTargetOrderProjection,
                CtpVerifiedOrderTargetProjection,
            )

            if type(target_handle) is not CtpOrderTargetProjectionHandle:
                raise ValueError("exact same-store target handle required")
            projection = store.read_ctp_order_target_projection(scope, target_handle)
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "fresh same-store verified CTP target is unavailable"
            ) from error
        if type(projection) is not CtpVerifiedOrderTargetProjection:
            raise CtpI9ParentRequestBuilderError("typed CTP target readback is unavailable")
        instrument, order_ref, exchange, order_sys_id, front_id, session_id = (
            _validate_cancel_payload(payload, detached)
        )
        reservation = store.read_ctp_order_identity(scope, detached.managed_intent_id)
        if type(reservation) is not i9[2] or reservation != detached.order_ref_reservation:
            raise CtpI9ParentRequestBuilderError("same-store I9 reservation readback differs")
        expected_target = (
            reservation.account_key,
            reservation.scope_key,
            reservation.trading_day,
            reservation.managed_intent_id,
            reservation.runtime_order_id,
            reservation.order_ref,
            detached.session_generation_id,
            detached.dispatch_front_id,
            detached.dispatch_session_id,
            instrument,
            exchange,
            order_sys_id,
            front_id,
            session_id,
        )
        observed_target = (
            projection.account_key,
            projection.scope_key,
            projection.trading_day,
            projection.managed_intent_id,
            projection.runtime_order_id,
            projection.order_ref,
            projection.session_generation_id,
            projection.query_front_id,
            projection.query_session_id,
            projection.instrument_id,
            projection.exchange_id,
            projection.order_sys_id,
            projection.front_id,
            projection.session_id,
        )
        if expected_target != observed_target:
            raise CtpI9ParentRequestBuilderError(
                "fresh I9 target projection differs from prepared cancel action"
            )
        try:
            source_binding = worker.stage_prepared_dispatch(
                detached,
                cancel_target_projection=target_handle,
            )
            if type(source_binding) is not i9[5]:
                raise ValueError("I9 worker returned an untyped cancel binding")
            binding = _binding_from_i9(source_binding)
            _require_binding_matches_prepared(binding, detached, reservation, scope)
            command = store.read_ctp_dispatch_command(scope, detached.command_id)
            current_reservation = store.read_ctp_order_identity(scope, detached.managed_intent_id)
            if type(current_reservation) is not i9[2] or current_reservation != reservation:
                raise ValueError("I9 reservation changed during cancel staging")
            _assert_command_row_matches(command, binding)
            projection_row = store.read_ctp_dispatch_projection(scope, detached.command_id)
            if type(command) is not i9[7] or type(projection_row) is not i9[6]:
                raise ValueError("I9 cancel readback is untyped")
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "I9 cancel staging/readback failed closed"
            ) from error
        try:
            from bt_api_execution.contracts import payload_sha256

            expected_native_payload = {**payload, "OrderActionRef": binding.native_action_ref}
            expected_native_payload_sha256 = payload_sha256(expected_native_payload)
        except Exception as error:
            raise CtpI9ParentRequestBuilderError(
                "I9 native cancel payload fingerprint is unavailable"
            ) from error
        cancel_action = getattr(projection_row, "cancel_action", None)
        target_action = getattr(cancel_action, "target_order", None)
        projected_order_state = getattr(target_action, "order_state", None)
        self._assert_cancel_order_state_matches_verified_target(
            projected_order_state,
            verified_provider_state=projection.provider_state,
            projected_order_state_type=CtpProjectedOrderState,
        )
        expected_target_projection = CtpTargetOrderProjection(
            managed_intent_id=detached.managed_intent_id,
            runtime_order_id=detached.runtime_order_id,
            order_ref=reservation.order_ref,
            exchange_id=exchange,
            order_sys_id=order_sys_id,
            front_id=front_id,
            session_id=session_id,
            order_state=projected_order_state,
        )
        expected_cancel_action = CtpCancelActionProjection(
            managed_action_id=detached.managed_cancel_intent_id,
            action_state=None,
            terminal=None,
            source_kind=None,
            updated_at_ns=None,
            target_order=expected_target_projection,
        )
        expected_projection = CtpDispatchProjection(
            command_id=detached.command_id,
            operation="CANCEL",
            command_status="READY",
            local_dispatch_outcome=None,
            unknown_reason=None,
            submit_action=None,
            cancel_action=expected_cancel_action,
            unknown_resolution=None,
            local_queue_receipt_id=binding.local_queue_receipt_id,
            local_queue_receipt_queued=None,
        )
        if (
            type(projection_row) is not CtpDispatchProjection
            or not _typed_dataclass_equal(projection_row, expected_projection)
            or type(cancel_action) is not CtpCancelActionProjection
            or type(getattr(cancel_action, "target_order", None)) is not CtpTargetOrderProjection
            or command is None
            or command.operation != "CANCEL"
            or command.status != "READY"
            or command.request_payload_sha256 != payload_digest
            or not _typed_equal(dict(command.request_payload), payload)
            or binding.request_payload_sha256 != payload_digest
            or not _typed_equal(binding.request_payload, payload)
            or type(binding.native_action_ref) is not int
            or not 1 <= binding.native_action_ref <= 2_147_483_647
            or not _typed_equal(
                binding.native_request_payload,
                expected_native_payload,
            )
            or binding.native_request_payload_sha256 != expected_native_payload_sha256
            or command.native_request_payload_sha256 != expected_native_payload_sha256
            or not _typed_equal(command.native_request_payload, expected_native_payload)
        ):
            raise CtpI9ParentRequestBuilderError(
                "staged I9 cancel row differs from canonical facts"
            )
        mirror = self._parent_reservation_mirror(reservation, scope, parent)
        try:
            base_request = parent[2](
                symbol=instrument,
                account_id=scope.account_ref,
                order_id=order_sys_id,
                client_order_id=order_ref,
                order_ref=order_ref,
                exchange_id=exchange,
                front_id=front_id,
                session_id=session_id,
                idempotency_key=detached.command_id,
            )
            cancel_identity = self._parent_api.consume_ctp_cancel_dispatch_command(
                self._exchange_name,
                scope=scope,
                identity_store=store,
                command_id=detached.command_id,
                request=base_request,
            )
            if type(cancel_identity) is not parent[4]:
                raise ValueError("parent cancel identity echo is untyped")
            parent_request = replace(base_request, ctp_cancel_identity=cancel_identity)
        except Exception as error:
            raise CtpI9ParentRequestBuilderError("parent cancel DTO echo failed closed") from error
        cancel_identity = parent_request.ctp_cancel_identity
        expected_cancel_identity = {
            "version": 2,
            "environment": scope.environment,
            "account_id": scope.account_ref,
            "instrument_id": instrument,
            "account_key": reservation.account_key,
            "trading_day": reservation.trading_day,
            "scope_key": reservation.scope_key,
            "managed_intent_id": reservation.managed_intent_id,
            "runtime_order_id": reservation.runtime_order_id,
            "order_ref": reservation.order_ref,
            "command_id": detached.command_id,
            "request_payload_sha256": payload_digest,
            "native_request_payload_sha256": binding.native_request_payload_sha256,
            "managed_action_id": detached.managed_cancel_intent_id,
            "approval_use_id": detached.approval_use_id,
            "approval_digest": detached.approval_digest,
            "session_binding_sha256": binding.session_binding_sha256,
            "session_generation_id": detached.session_generation_id,
            "dispatch_front_id": detached.dispatch_front_id,
            "dispatch_session_id": detached.dispatch_session_id,
            "native_request_id": detached.native_request_id,
            "native_action_ref": binding.native_action_ref,
            "cancel_target_order_ref": reservation.order_ref,
            "cancel_target_exchange_id": exchange,
            "cancel_target_order_sys_id": order_sys_id,
            "cancel_target_front_id": front_id,
            "cancel_target_session_id": session_id,
        }
        if (
            type(cancel_identity) is not parent[4]
            or any(
                not _typed_equal(getattr(cancel_identity, name), expected)
                for name, expected in expected_cancel_identity.items()
            )
            or cancel_identity.dispatch_authorized is not False
        ):
            raise CtpI9ParentRequestBuilderError("parent cancel DTO lost exact I9 identity")
        return CtpI9ParentRequestContract(
            operation="cancel",
            prepared_dispatch=detached,
            i9_dispatch_binding=binding,
            parent_request=parent_request,
            canonical_request_payload_json=payload_json,
            request_payload_sha256=payload_digest,
            parent_reservation_mirror=mirror,
        )

    @staticmethod
    def _assert_cancel_order_state_matches_verified_target(
        order_state: Any,
        *,
        verified_provider_state: Any,
        projected_order_state_type: type,
    ) -> None:
        """Bind the durable callback projection to the fresh open-order query.

        I9 intentionally keeps callback/reconciliation order state separate
        from the fresh target query. A fresh ``OPEN``/``PARTIAL`` target may
        therefore have no local callback projection yet. When one exists, it
        must be a well-formed nonterminal state that cannot contradict the
        current target: an ``ACKNOWLEDGED`` projection may lag either query
        state, while ``PARTIALLY_FILLED`` requires a current partial target.
        Terminal or mismatched rows reject before the parent DTO is mirrored.
        """

        if type(order_state) is not projected_order_state_type:
            raise CtpI9ParentRequestBuilderError("I9 cancel target order state readback is untyped")
        if verified_provider_state not in {"OPEN", "PARTIAL"}:
            raise CtpI9ParentRequestBuilderError("fresh I9 cancel target is not open or partial")
        if order_state.provider_state is None:
            if any(
                value is not None
                for value in (
                    order_state.terminal,
                    order_state.source_kind,
                    order_state.updated_at_ns,
                )
            ):
                raise CtpI9ParentRequestBuilderError(
                    "I9 cancel target has a partial absent order projection"
                )
            return
        if (
            type(order_state.provider_state) is not str
            or type(order_state.terminal) is not bool
            or order_state.terminal is not False
            or order_state.source_kind not in {"CALLBACK", "RECONCILIATION"}
            or type(order_state.updated_at_ns) is not int
            or order_state.updated_at_ns <= 0
        ):
            raise CtpI9ParentRequestBuilderError(
                "I9 cancel target order projection is terminal or malformed"
            )
        allowed_projected_states = {
            "OPEN": {"ACKNOWLEDGED"},
            "PARTIAL": {"ACKNOWLEDGED", "PARTIALLY_FILLED"},
        }
        if order_state.provider_state not in allowed_projected_states[verified_provider_state]:
            raise CtpI9ParentRequestBuilderError(
                "I9 cancel order projection conflicts with fresh target state"
            )
