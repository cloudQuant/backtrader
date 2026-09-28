"""Narrow managed-execution delegation port for :class:`BtApiStore`.

The port deliberately owns neither a provider client nor a journal.  A trusted
runtime composition supplies an adapter only after it has validated the
mandatory Iteration 41 configuration and its sealed capability contract.  The
Store gives that adapter a private legacy dispatch callable solely so the
adapter can invoke it *after* durable admission; a failure in the adapter is
never retried through the legacy path by the Store.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Optional, Protocol


class ManagedExecutionAdapterError(RuntimeError):
    """A supplied managed adapter is absent, malformed, or cannot project an action."""


class CtpManagedProjectionState(str, Enum):
    """Non-provider states a durable CTP projection may expose to Backtrader."""

    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    LOCAL_REJECTED = "LOCAL_REJECTED"


def ctp_managed_command_id(
    operation: str,
    managed_intent_id: str,
    runtime_order_id: str,
    managed_cancel_intent_id: Optional[str] = None,
) -> str:
    """Return the one versioned command key shared by Store and outbox.

    The runtime order identity is already scoped to the sealed execution scope.
    The complete scope and trading-day values are still echoed and validated in
    :class:`CtpManagedDispatchBinding`; they are not omitted from the durable
    command row merely because they do not participate in this stable key.
    """

    if operation not in ("submit", "cancel"):
        raise ManagedExecutionAdapterError("managed CTP command operation is invalid")
    _managed_identity_text(managed_intent_id, "managed_intent_id")
    _managed_identity_text(runtime_order_id, "runtime_order_id")
    cancel_id = managed_cancel_intent_id or ""
    if operation == "submit" and cancel_id:
        raise ManagedExecutionAdapterError("managed CTP submit cannot have a cancel identity")
    if operation == "cancel":
        _managed_identity_text(cancel_id, "managed_cancel_intent_id")
    material = "\0".join(
        (
            "backtrader.ctp.managed-outbox.v1",
            operation,
            managed_intent_id,
            runtime_order_id,
            cancel_id,
        )
    )
    try:
        digest = hashlib.sha256(material.encode("ascii")).hexdigest()
    except UnicodeEncodeError as error:
        raise ManagedExecutionAdapterError("managed CTP command identity is not ASCII") from error
    return "ctp-outbox-v1:" + digest


def _managed_sha256(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ManagedExecutionAdapterError("managed CTP " + name + " digest is invalid")
    return value


def _managed_payload_sha256(value: Mapping[str, Any], name: str) -> str:
    if not isinstance(value, Mapping) or not value:
        raise ManagedExecutionAdapterError("managed CTP " + name + " must be a non-empty mapping")
    try:
        payload = json.dumps(
            _managed_thaw_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ManagedExecutionAdapterError(
            "managed CTP " + name + " is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _managed_freeze_json(value: Any) -> Any:
    """Recursively freeze the canonical JSON subset used in dispatch bindings."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _managed_freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_managed_freeze_json(item) for item in value)
    return value


def _managed_thaw_json(value: Any) -> Any:
    """Return a detached JSON-shaped value from an immutable binding field."""

    if isinstance(value, Mapping):
        return {key: _managed_thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_managed_thaw_json(item) for item in value]
    return value


# This module is on Backtrader's default import path, including Python 3.8/3.9.
# Keep slots on the newer interpreters used by the optional managed SDK.
_BINDING_DATACLASS_OPTIONS = {"slots": True} if sys.version_info >= (3, 10) else {}


@dataclass(frozen=True, **_BINDING_DATACLASS_OPTIONS)
class CtpManagedDispatchBinding:
    """Exact V2 Store-to-outbox binding for one managed CTP action.

    This is an identity envelope, not an approval capability or provider
    observation. The logical request is retained separately from the native
    request: for cancellation, the Store adds its allocated integer
    ``OrderActionRef`` only after staging. The managed action ID remains a
    distinct opaque string. A code-owned outbox must derive both payloads and
    their digests from its durable row and echo the Store's queue receipt ID
    unchanged.
    """

    operation: str
    command_id: str
    account_key: str
    scope_key: str
    trading_day: str
    managed_intent_id: str
    runtime_order_id: str
    managed_action_id: str
    order_ref: str
    cancel_target_order_ref: Optional[str]
    request_payload_sha256: str
    request_payload: Mapping[str, Any]
    native_request_payload_sha256: str
    native_request_payload: Mapping[str, Any]
    approval_use_id: str
    approval_digest: str
    session_binding_sha256: str
    session_binding: Mapping[str, Any]
    session_generation_id: str
    dispatch_front_id: int
    dispatch_session_id: int
    native_request_id: int
    native_action_ref: Optional[int]
    local_queue_receipt_id: str
    order_ref_reservation_created_at_ns: int
    local_queue_receipt_queued: Optional[bool] = None
    managed_cancel_intent_id: Optional[str] = None
    cancel_target_exchange_id: Optional[str] = None
    cancel_target_order_sys_id: Optional[str] = None
    cancel_target_front_id: Optional[int] = None
    cancel_target_session_id: Optional[int] = None
    version: int = 2

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 2:
            raise ManagedExecutionAdapterError("managed CTP dispatch binding version is invalid")
        if self.operation not in ("submit", "cancel"):
            raise ManagedExecutionAdapterError("managed CTP dispatch binding operation is invalid")
        expected_command_id = ctp_managed_command_id(
            self.operation,
            self.managed_intent_id,
            self.runtime_order_id,
            self.managed_cancel_intent_id,
        )
        if self.command_id != expected_command_id:
            raise ManagedExecutionAdapterError("managed CTP dispatch command key does not match")
        for name in ("account_key", "scope_key", "managed_action_id", "approval_use_id"):
            _managed_identity_text(getattr(self, name), name)
        if type(self.trading_day) is not str or (
            len(self.trading_day) != 8
            or not self.trading_day.isascii()
            or not self.trading_day.isdigit()
        ):
            raise ManagedExecutionAdapterError("managed CTP dispatch trading day is invalid")
        _managed_identity_text(self.managed_intent_id, "managed_intent_id")
        if (
            type(self.runtime_order_id) is not str
            or len(self.runtime_order_id) != len("bt-managed-v1:") + 64
            or not self.runtime_order_id.startswith("bt-managed-v1:")
            or any(character not in "0123456789abcdef" for character in self.runtime_order_id[14:])
        ):
            raise ManagedExecutionAdapterError("managed CTP dispatch runtime order ID is invalid")
        if (
            type(self.order_ref) is not str
            or len(self.order_ref) != 12
            or not self.order_ref.isascii()
            or not self.order_ref.isdigit()
        ):
            raise ManagedExecutionAdapterError("managed CTP dispatch OrderRef is invalid")
        _managed_sha256(self.request_payload_sha256, "request payload")
        if _managed_payload_sha256(self.request_payload, "request payload") != (
            self.request_payload_sha256
        ):
            raise ManagedExecutionAdapterError("managed CTP request payload digest differs")
        if (
            _managed_payload_sha256(self.native_request_payload, "native request payload")
            != self.native_request_payload_sha256
        ):
            raise ManagedExecutionAdapterError("managed CTP native request payload digest differs")
        if "OrderActionRef" in self.request_payload:
            raise ManagedExecutionAdapterError(
                "managed CTP logical request cannot contain native ActionRef"
            )
        _managed_sha256(self.approval_digest, "approval")
        _managed_sha256(self.session_binding_sha256, "session binding")
        if _managed_payload_sha256(self.session_binding, "session binding") != (
            self.session_binding_sha256
        ):
            raise ManagedExecutionAdapterError("managed CTP session binding digest differs")
        object.__setattr__(self, "request_payload", _managed_freeze_json(self.request_payload))
        object.__setattr__(
            self, "native_request_payload", _managed_freeze_json(self.native_request_payload)
        )
        object.__setattr__(self, "session_binding", _managed_freeze_json(self.session_binding))
        _managed_identity_text(self.session_generation_id, "session_generation_id")
        for value, name in (
            (self.dispatch_front_id, "dispatch FrontID"),
            (self.dispatch_session_id, "dispatch SessionID"),
            (self.native_request_id, "native RequestID"),
        ):
            if type(value) is not int or value <= 0 or value > 2_147_483_647:
                raise ManagedExecutionAdapterError("managed CTP " + name + " is invalid")
        if (
            type(self.local_queue_receipt_id) is not str
            or len(self.local_queue_receipt_id) != 32
            or any(character not in "0123456789abcdef" for character in self.local_queue_receipt_id)
        ):
            raise ManagedExecutionAdapterError("managed CTP queue receipt ID is invalid")
        if type(self.order_ref_reservation_created_at_ns) is not int or (
            self.order_ref_reservation_created_at_ns <= 0
        ):
            raise ManagedExecutionAdapterError(
                "managed CTP OrderRef reservation timestamp is invalid"
            )
        if (
            self.local_queue_receipt_queued is not None
            and type(self.local_queue_receipt_queued) is not bool
        ):
            raise ManagedExecutionAdapterError("managed CTP queue receipt disposition is invalid")
        if "RequestID" in self.request_payload and (
            type(self.request_payload["RequestID"]) is not int
            or self.request_payload["RequestID"] != self.native_request_id
        ):
            raise ManagedExecutionAdapterError(
                "managed CTP logical request RequestID differs from its native identity"
            )
        if self.operation == "submit":
            if self.managed_action_id != self.managed_intent_id:
                raise ManagedExecutionAdapterError("managed CTP submit action identity differs")
            if self.managed_cancel_intent_id is not None:
                raise ManagedExecutionAdapterError("managed CTP submit has cancel identity")
            if self.native_action_ref is not None:
                raise ManagedExecutionAdapterError("managed CTP submit cannot carry ActionRef")
            if self.native_request_payload_sha256 != self.request_payload_sha256:
                raise ManagedExecutionAdapterError(
                    "managed CTP submit native payload differs from logical payload"
                )
            if self.cancel_target_order_ref is not None:
                raise ManagedExecutionAdapterError(
                    "managed CTP submit cannot carry target OrderRef"
                )
            if any(
                value is not None
                for value in (
                    self.cancel_target_exchange_id,
                    self.cancel_target_order_sys_id,
                    self.cancel_target_front_id,
                    self.cancel_target_session_id,
                )
            ):
                raise ManagedExecutionAdapterError("managed CTP submit cannot carry cancel target")
        else:
            _managed_identity_text(self.managed_cancel_intent_id, "managed_cancel_intent_id")
            if self.managed_action_id != self.managed_cancel_intent_id:
                raise ManagedExecutionAdapterError("managed CTP cancel action identity differs")
            if self.managed_action_id == self.managed_intent_id:
                raise ManagedExecutionAdapterError("managed CTP cancel action must be distinct")
            if (
                type(self.native_action_ref) is not int
                or not 1 <= self.native_action_ref <= 2_147_483_647
            ):
                raise ManagedExecutionAdapterError("managed CTP native ActionRef is invalid")
            if (
                type(self.cancel_target_order_ref) is not str
                or self.cancel_target_order_ref != self.order_ref
            ):
                raise ManagedExecutionAdapterError("managed CTP cancel target OrderRef differs")
            _managed_identity_text(self.cancel_target_exchange_id, "cancel target ExchangeID")
            _managed_identity_text(self.cancel_target_order_sys_id, "cancel target OrderSysID")
            for value, name in (
                (self.cancel_target_front_id, "cancel target FrontID"),
                (self.cancel_target_session_id, "cancel target SessionID"),
            ):
                if type(value) is not int or value <= 0 or value > 2_147_483_647:
                    raise ManagedExecutionAdapterError("managed CTP " + name + " is invalid")
        expected_session = {
            "session_generation_id": self.session_generation_id,
            "dispatch_front_id": self.dispatch_front_id,
            "dispatch_session_id": self.dispatch_session_id,
        }
        if any(self.session_binding.get(key) != value for key, value in expected_session.items()):
            raise ManagedExecutionAdapterError("managed CTP session keys do not match binding")
        if self.request_payload.get("OrderRef") != self.order_ref:
            raise ManagedExecutionAdapterError("managed CTP request does not echo OrderRef")
        if self.operation == "cancel":
            native_request_payload = dict(self.request_payload)
            native_request_payload["OrderActionRef"] = self.native_action_ref
            if (
                _managed_payload_sha256(native_request_payload, "native request payload")
                != self.native_request_payload_sha256
            ):
                raise ManagedExecutionAdapterError(
                    "managed CTP cancel native payload differs from Store ActionRef"
                )
            cancel_echoes = {
                "ExchangeID": self.cancel_target_exchange_id,
                "OrderSysID": self.cancel_target_order_sys_id,
                "FrontID": self.cancel_target_front_id,
                "SessionID": self.cancel_target_session_id,
            }
            if any(
                self.request_payload.get(key) != value
                or type(self.request_payload.get(key)) is not type(value)
                for key, value in cancel_echoes.items()
            ):
                raise ManagedExecutionAdapterError(
                    "managed CTP cancel request does not echo its exact target binding"
                )

    def to_store_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "operation": self.operation,
            "command_id": self.command_id,
            "account_key": self.account_key,
            "scope_key": self.scope_key,
            "trading_day": self.trading_day,
            "managed_intent_id": self.managed_intent_id,
            "runtime_order_id": self.runtime_order_id,
            "managed_action_id": self.managed_action_id,
            "order_ref": self.order_ref,
            "cancel_target_order_ref": self.cancel_target_order_ref,
            "request_payload_sha256": self.request_payload_sha256,
            "request_payload": _managed_thaw_json(self.request_payload),
            "native_request_payload_sha256": self.native_request_payload_sha256,
            "native_request_payload": _managed_thaw_json(self.native_request_payload),
            "approval_use_id": self.approval_use_id,
            "approval_digest": self.approval_digest,
            "session_binding_sha256": self.session_binding_sha256,
            "session_binding": _managed_thaw_json(self.session_binding),
            "session_generation_id": self.session_generation_id,
            "dispatch_front_id": self.dispatch_front_id,
            "dispatch_session_id": self.dispatch_session_id,
            "native_request_id": self.native_request_id,
            "native_action_ref": self.native_action_ref,
            "local_queue_receipt_id": self.local_queue_receipt_id,
            "order_ref_reservation_created_at_ns": self.order_ref_reservation_created_at_ns,
            "local_queue_receipt_queued": self.local_queue_receipt_queued,
            "managed_cancel_intent_id": self.managed_cancel_intent_id,
            "cancel_target_exchange_id": self.cancel_target_exchange_id,
            "cancel_target_order_sys_id": self.cancel_target_order_sys_id,
            "cancel_target_front_id": self.cancel_target_front_id,
            "cancel_target_session_id": self.cancel_target_session_id,
        }

    @classmethod
    def from_store_payload(cls, value: Any) -> "CtpManagedDispatchBinding":
        fields = {
            "version",
            "operation",
            "command_id",
            "account_key",
            "scope_key",
            "trading_day",
            "managed_intent_id",
            "runtime_order_id",
            "managed_action_id",
            "order_ref",
            "cancel_target_order_ref",
            "request_payload_sha256",
            "request_payload",
            "native_request_payload_sha256",
            "native_request_payload",
            "approval_use_id",
            "approval_digest",
            "session_binding_sha256",
            "session_binding",
            "session_generation_id",
            "dispatch_front_id",
            "dispatch_session_id",
            "native_request_id",
            "native_action_ref",
            "local_queue_receipt_id",
            "order_ref_reservation_created_at_ns",
            "local_queue_receipt_queued",
            "managed_cancel_intent_id",
            "cancel_target_exchange_id",
            "cancel_target_order_sys_id",
            "cancel_target_front_id",
            "cancel_target_session_id",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ManagedExecutionAdapterError("managed CTP dispatch binding shape is invalid")
        try:
            return cls(**dict(value))
        except TypeError as error:
            raise ManagedExecutionAdapterError("managed CTP dispatch binding is invalid") from error


@dataclass(frozen=True)
class CtpManagedExecutionProjection:
    """One durable, non-provider projection returned by a managed CTP adapter.

    ``durable_projection_id`` names the ledger row the adapter claims to have
    read. The Store can validate this value's shape and identity echoes, but
    this Python type does not prove that a row was committed or recovered.
    A future CTP adapter must read the projection from the single execution
    ledger/outbox before returning it. This value intentionally has no provider
    order ID, fill, ACK, or native receipt field. ``local_queue_receipt_id``
    correlates transport only; it is never evidence that the CTP front accepted
    an action. ``PENDING`` and ``UNKNOWN`` remain nonterminal until a separate,
    typed provider-callback observation is available. Until that durable outbox
    read and callback evidence exist, this projection is only a nonauthorizing
    structural contract.
    """

    operation: str
    state: CtpManagedProjectionState
    durable_projection_id: str
    managed_intent_id: str
    runtime_order_id: str
    managed_cancel_intent_id: Optional[str] = None
    local_queue_receipt_id: Optional[str] = None
    error_code: Optional[str] = None
    dispatch_binding: Optional[CtpManagedDispatchBinding] = None
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version not in (1, 2):
            raise ManagedExecutionAdapterError("managed CTP projection version is invalid")
        if type(self.operation) is not str or self.operation not in ("submit", "cancel"):
            raise ManagedExecutionAdapterError("managed CTP projection operation is invalid")
        try:
            state = CtpManagedProjectionState(self.state)
        except (TypeError, ValueError) as error:
            raise ManagedExecutionAdapterError("managed CTP projection state is invalid") from error
        object.__setattr__(self, "state", state)
        _managed_identity_text(self.durable_projection_id, "durable_projection_id")
        _managed_identity_text(self.managed_intent_id, "managed_intent_id")
        if (
            type(self.runtime_order_id) is not str
            or len(self.runtime_order_id) != len("bt-managed-v1:") + 64
            or not self.runtime_order_id.startswith("bt-managed-v1:")
            or any(character not in "0123456789abcdef" for character in self.runtime_order_id[14:])
        ):
            raise ManagedExecutionAdapterError("managed CTP projection runtime_order_id is invalid")
        if self.operation == "cancel":
            _managed_identity_text(self.managed_cancel_intent_id, "managed_cancel_intent_id")
        elif self.managed_cancel_intent_id is not None:
            raise ManagedExecutionAdapterError(
                "managed CTP submit projection cannot contain a cancel identity"
            )
        if self.local_queue_receipt_id is not None and (
            type(self.local_queue_receipt_id) is not str
            or len(self.local_queue_receipt_id) != 32
            or any(character not in "0123456789abcdef" for character in self.local_queue_receipt_id)
        ):
            raise ManagedExecutionAdapterError("managed CTP local queue receipt ID is invalid")
        if self.error_code is not None:
            _managed_identity_text(self.error_code, "projection error_code")
        if self.version == 1 and self.dispatch_binding is not None:
            raise ManagedExecutionAdapterError(
                "managed CTP legacy projection cannot carry a v2 dispatch binding"
            )
        if self.version == 2 and type(self.dispatch_binding) is not CtpManagedDispatchBinding:
            raise ManagedExecutionAdapterError(
                "managed CTP projection lacks its typed dispatch binding"
            )
        if self.dispatch_binding is not None:
            if (
                self.dispatch_binding.operation != self.operation
                or self.dispatch_binding.command_id != self.durable_projection_id
                or self.dispatch_binding.managed_intent_id != self.managed_intent_id
                or self.dispatch_binding.runtime_order_id != self.runtime_order_id
                or self.dispatch_binding.managed_cancel_intent_id != self.managed_cancel_intent_id
                or self.dispatch_binding.local_queue_receipt_id != self.local_queue_receipt_id
            ):
                raise ManagedExecutionAdapterError("managed CTP projection binding does not match")
        if (
            self.version == 2
            and state is CtpManagedProjectionState.PENDING
            and (self.dispatch_binding.local_queue_receipt_queued is not True)
        ):
            raise ManagedExecutionAdapterError(
                "managed CTP pending projection lacks queued receipt"
            )
        if (
            self.version == 2
            and state is CtpManagedProjectionState.LOCAL_REJECTED
            and (self.dispatch_binding.local_queue_receipt_queued is not False)
        ):
            raise ManagedExecutionAdapterError("managed CTP rejection lacks rejected queue receipt")
        if state is CtpManagedProjectionState.LOCAL_REJECTED and not self.error_code:
            raise ManagedExecutionAdapterError("managed CTP local rejection requires an error code")

    def to_store_response(self) -> dict[str, Any]:
        """Return the fixed Store/Broker envelope for this durable projection."""

        response = {
            "kind": "managed_execution_projection",
            "version": self.version,
            "projection_id": self.durable_projection_id,
            "operation": self.operation,
            "state": self.state.value,
            "managed_intent_id": self.managed_intent_id,
            "runtime_order_id": self.runtime_order_id,
            "managed_cancel_intent_id": self.managed_cancel_intent_id,
            "local_queue_receipt_id": self.local_queue_receipt_id,
            "status": (
                "local_rejected"
                if self.state is CtpManagedProjectionState.LOCAL_REJECTED
                else self.state.value.lower()
            ),
            "execution_unknown": self.state is CtpManagedProjectionState.UNKNOWN,
            "error_code": self.error_code,
        }
        if self.dispatch_binding is not None:
            response["dispatch_binding"] = self.dispatch_binding.to_store_payload()
        return response


_CTP_MANAGED_PROJECTION_FIELDS = frozenset(
    {
        "kind",
        "version",
        "projection_id",
        "operation",
        "state",
        "managed_intent_id",
        "runtime_order_id",
        "managed_cancel_intent_id",
        "local_queue_receipt_id",
        "status",
        "execution_unknown",
        "error_code",
    }
)
_CTP_MANAGED_PROJECTION_V2_FIELDS = _CTP_MANAGED_PROJECTION_FIELDS | {"dispatch_binding"}


def parse_ctp_managed_execution_projection(
    value: Any, *, expected_operation: Optional[str] = None
) -> Optional[CtpManagedExecutionProjection]:
    """Parse the exact non-provider Store envelope, returning ``None`` otherwise."""

    if not isinstance(value, Mapping) or value.get("kind") != "managed_execution_projection":
        return None
    version = value.get("version")
    expected_fields = (
        _CTP_MANAGED_PROJECTION_FIELDS
        if version == 1
        else _CTP_MANAGED_PROJECTION_V2_FIELDS if version == 2 else frozenset()
    )
    if set(value) != expected_fields:
        raise ManagedExecutionAdapterError("managed CTP projection envelope has an invalid shape")
    projection = CtpManagedExecutionProjection(
        operation=value["operation"],
        state=value["state"],
        durable_projection_id=value["projection_id"],
        managed_intent_id=value["managed_intent_id"],
        runtime_order_id=value["runtime_order_id"],
        managed_cancel_intent_id=value["managed_cancel_intent_id"],
        local_queue_receipt_id=value["local_queue_receipt_id"],
        error_code=value["error_code"],
        dispatch_binding=(
            CtpManagedDispatchBinding.from_store_payload(value["dispatch_binding"])
            if version == 2
            else None
        ),
        version=value["version"],
    )
    if expected_operation is not None and projection.operation != expected_operation:
        raise ManagedExecutionAdapterError("managed CTP projection operation does not match")
    expected_status = (
        "local_rejected"
        if projection.state is CtpManagedProjectionState.LOCAL_REJECTED
        else projection.state.value.lower()
    )
    if (
        value["status"] != expected_status
        or type(value["execution_unknown"]) is not bool
        or value["execution_unknown"] is not (projection.state is CtpManagedProjectionState.UNKNOWN)
    ):
        raise ManagedExecutionAdapterError("managed CTP projection state echo is invalid")
    return projection


def require_ctp_managed_execution_projection(
    value: Any,
    *,
    operation: str,
    managed_intent_id: str,
    runtime_order_id: str,
    managed_cancel_intent_id: Optional[str] = None,
    local_queue_receipt: Any = None,
) -> CtpManagedExecutionProjection:
    """Require the adapter result to be a matching durable projection.

    A raw ``command_receipt`` or a runtime queue classifier is deliberately
    rejected here, even if it says ``UNKNOWN``. Only a durable projection may
    leave the managed Store method as its final result.
    """

    if type(value) is not CtpManagedExecutionProjection:
        raise ManagedExecutionAdapterError(
            "managed CTP adapter must return a typed durable projection"
        )
    if (
        value.operation != operation
        or value.managed_intent_id != managed_intent_id
        or value.runtime_order_id != runtime_order_id
        or value.managed_cancel_intent_id != managed_cancel_intent_id
    ):
        raise ManagedExecutionAdapterError(
            "managed CTP projection identity does not match dispatch"
        )
    if local_queue_receipt is None:
        return value
    if not isinstance(local_queue_receipt, Mapping):
        raise ManagedExecutionAdapterError("managed CTP Store queue receipt is malformed")
    receipt_id = local_queue_receipt.get("receipt_id")
    queued = local_queue_receipt.get("queued")
    if (
        local_queue_receipt.get("kind") != "command_receipt"
        or local_queue_receipt.get("command") != operation
        or type(receipt_id) is not str
        or len(receipt_id) != 32
        or any(character not in "0123456789abcdef" for character in receipt_id)
        or type(queued) is not bool
        or value.local_queue_receipt_id != receipt_id
    ):
        raise ManagedExecutionAdapterError(
            "managed CTP projection does not echo its local queue receipt"
        )
    if queued is True and value.state is CtpManagedProjectionState.LOCAL_REJECTED:
        raise ManagedExecutionAdapterError(
            "managed CTP queued command cannot be projected as locally rejected"
        )
    if queued is False and value.state is not CtpManagedProjectionState.LOCAL_REJECTED:
        raise ManagedExecutionAdapterError(
            "managed CTP rejected queue cannot be projected as pending"
        )
    return value


def _managed_identity_text(value: Any, name: str) -> str:
    """Validate a bounded identity token before it crosses the Store boundary."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 128
        or not value.isascii()
        or any(not (character.isalnum() or character in "._:-") for character in value)
    ):
        raise ManagedExecutionAdapterError("managed CTP " + name + " is invalid")
    return value


@dataclass(frozen=True)
class CtpManagedOrderDispatch:
    """Canonical CTP order plus runtime-owned durable identity.

    Code-owned runtime composition creates this value only from an admitted
    managed intent. The Store accepts it at its SDK queue boundary and never
    translates it to the legacy native CTP wrapper.
    """

    order: Any
    managed_intent_id: str
    runtime_order_id: str
    hedge_flag: str

    def __post_init__(self) -> None:
        _managed_identity_text(self.managed_intent_id, "managed_intent_id")
        if (
            type(self.runtime_order_id) is not str
            or len(self.runtime_order_id) != len("bt-managed-v1:") + 64
            or not self.runtime_order_id.startswith("bt-managed-v1:")
            or any(character not in "0123456789abcdef" for character in self.runtime_order_id[14:])
        ):
            raise ManagedExecutionAdapterError("managed CTP runtime_order_id is invalid")
        if type(self.hedge_flag) is not str or self.hedge_flag not in ("1", "2", "3"):
            raise ManagedExecutionAdapterError("managed CTP hedge_flag is invalid")


@dataclass(frozen=True)
class CtpManagedCancelDispatch:
    """Durable CTP cancel identity resolved by the SDK from one order binding."""

    managed_intent_id: str
    runtime_order_id: str
    managed_cancel_intent_id: str

    def __post_init__(self) -> None:
        _managed_identity_text(self.managed_intent_id, "managed_intent_id")
        if (
            type(self.runtime_order_id) is not str
            or len(self.runtime_order_id) != len("bt-managed-v1:") + 64
            or not self.runtime_order_id.startswith("bt-managed-v1:")
            or any(character not in "0123456789abcdef" for character in self.runtime_order_id[14:])
        ):
            raise ManagedExecutionAdapterError("managed CTP runtime_order_id is invalid")
        _managed_identity_text(self.managed_cancel_intent_id, "managed_cancel_intent_id")


class CtpRuntimeExecutionAdapter(Protocol):
    """Typed, pre-authorized CTP adapter composed by code-owned runtime.

    Its dispatch callback accepts only the frozen contracts above. This keeps
    managed CTP writes on the SDK queue and gives this Store no raw native
    order/action identifier to pass to its historical CTP wrapper.
    """

    ctp_managed_execution_version: int

    def submit_order(
        self,
        order: Any,
        sdk_dispatch: Callable[[CtpManagedOrderDispatch], Any],
    ) -> Any:
        """Admit a managed intent before projecting it to the SDK queue."""

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        sdk_dispatch: Callable[[CtpManagedCancelDispatch], Any],
    ) -> Any:
        """Admit a managed cancellation before projecting it to the SDK queue."""


def require_ctp_runtime_execution_adapter(value: Any) -> CtpRuntimeExecutionAdapter:
    """Require the explicit typed adapter version used by managed CTP routes."""

    version = getattr(value, "ctp_managed_execution_version", None)
    if type(version) is not int or version != 1:
        raise ManagedExecutionAdapterError(
            "managed CTP execution requires the typed runtime adapter"
        )
    if not callable(getattr(value, "submit_order", None)):
        raise ManagedExecutionAdapterError("managed CTP adapter must implement submit_order")
    if not callable(getattr(value, "cancel_order", None)):
        raise ManagedExecutionAdapterError("managed CTP adapter must implement cancel_order")
    return value


class ManagedExecutionAdapter(Protocol):
    """The small explicit port accepted by :class:`BtApiStore`.

    The ``legacy_dispatch`` callables are private Store internals.  An adapter
    may call one once only after its own intent/journal/risk gates have made a
    durable decision.  It must not use an adapter failure as permission for
    the Store to route the framework action directly.
    """

    def submit_order(self, order: Any, legacy_dispatch: Callable[[Any], Any]) -> Any:
        """Return a normal Store response after a managed submission projection."""

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        legacy_dispatch: Callable[[Any, Optional[str]], Any],
    ) -> Any:
        """Return a normal Store response after a managed cancellation projection."""


def require_managed_execution_adapter(value: Any) -> Optional[ManagedExecutionAdapter]:
    """Validate a deliberate managed adapter attachment without importing optional packages."""

    if value is None:
        return None
    if not callable(getattr(value, "submit_order", None)):
        raise ManagedExecutionAdapterError("managed adapter must implement submit_order")
    return value


def require_managed_cancel(
    adapter: ManagedExecutionAdapter,
) -> Callable[[Any, Optional[str], Any], Any]:
    """Return the explicit cancellation port or fail closed before provider I/O."""

    cancel = getattr(adapter, "cancel_order", None)
    if not callable(cancel):
        raise ManagedExecutionAdapterError("managed adapter does not implement cancellation")
    return cancel
