"""Offline adapter contract for the isolated bt_api_execution I9 CTP outbox.

This module has no provider imports and is not registered by any runtime. It
joins the I9 OrderRef reservation and single-worker candidate to Backtrader's
strict v2 dispatch binding only when exact SDK classes are importable on Python
3.11+ and the worker's bound store is the same object used for durable
readback. Structural fake ports are non-authorizing. This is a local wiring
guard, not a security boundary against in-process tampering. Durable local
projections are not provider callback evidence, and cancel remains closed
without trusted typed order-projection provenance. No native, Gateway, or
bt_api_py fallback is provided here.

The normal ``BtApiStore._sdk_order_request`` seam is still intentionally
closed for managed CTP. It validates the runtime scope and then rejects before
reading or allocating through the separate SDK OrderRef ledger; it does not
accept an I9 reservation or a fully prepared I9 CTP dispatch. Likewise,
``_enqueue_order_command`` has no parameter carrying that staged dispatch and
currently rejects a managed identity before it reaches the v2 queue ports.
The low-level queue seam can prove receipt-before-publication only after a
prepared I9 dispatch exists. It cannot safely manufacture the approved native
request payload, action grant, or session binding from an ordinary Backtrader
``Order``. Until the Store exposes one injected builder that consumes the I9
reservation, returns the exact typed prepared request/binding, and passes its
receipt-writer/dispatcher into the v2 queue, the ordinary managed submit path
must remain fail-closed.
"""

from __future__ import annotations

import inspect
import re
import sys
from dataclasses import dataclass, replace
from datetime import date
from importlib.metadata import version
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple

from .managed_execution import (
    CtpManagedDispatchBinding,
    CtpManagedExecutionProjection,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    _managed_payload_sha256,
    ctp_managed_command_id,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ORDER_REF = re.compile(r"^[0-9]{12}$", re.ASCII)
_RECEIPT_ID = re.compile(r"^[0-9a-f]{32}$", re.ASCII)
_RUNTIME_ID = re.compile(r"^bt-managed-v1:[0-9a-f]{64}$", re.ASCII)


def _trusted_i9_types() -> Optional[Tuple[type, ...]]:
    """Load the reviewed I9 types only on its supported Python runtime.

    The SDK currently exposes no public same-store identity token. This
    optional bridge therefore accepts only the exact SDK classes and checks
    that the candidate's bound SQLite store is the very same object supplied
    for durable readback. This is a local wiring guard, not an in-process
    security boundary. Missing package/API or Python < 3.11 fails closed.
    """

    if sys.version_info < (3, 11):
        return None
    try:
        if version("bt_api_execution") != "0.2.0":
            return None
        from bt_api_execution.contracts import ExecutionScope
        from bt_api_execution.ctp_single_worker_candidate import (
            CtpManagedDispatchBinding as I9DispatchBinding,
            CtpManagedPreparedDispatch,
            CtpManagedSingleWorkerCandidate,
        )
        from bt_api_execution.store import (
            CtpDispatchCommand,
            CtpDispatchProjection,
            CtpOrderIdentityReservation,
            SqliteExecutionStore,
        )
    except Exception:
        return None
    return (
        ExecutionScope,
        SqliteExecutionStore,
        CtpOrderIdentityReservation,
        CtpManagedSingleWorkerCandidate,
        CtpManagedPreparedDispatch,
        I9DispatchBinding,
        CtpDispatchProjection,
        CtpDispatchCommand,
    )


class CtpI9OrderIdentityPort(Protocol):
    """Public OrderRef API implemented by I9 ``SqliteExecutionStore``."""

    def reserve_ctp_order_identity(
        self, scope: Any, managed_intent_id: str, runtime_order_id: str
    ) -> Any:
        """Allocate or idempotently return one durable same-account mapping."""

    def read_ctp_order_identity(self, scope: Any, managed_intent_id: str) -> Any:
        """Read one exact same-scope, same-day reservation without mutation."""

    def read_ctp_dispatch_command(self, scope: Any, command_id: str) -> Any:
        """Read the staged command row from this same durable store."""

    def read_ctp_dispatch_projection(self, scope: Any, command_id: str) -> Any:
        """Read the durable command projection from this same store."""


class CtpI9SingleWorkerPort(Protocol):
    """Public methods required from I9 ``CtpManagedSingleWorkerCandidate``."""

    def stage_prepared_dispatch(self, prepared: Any) -> Any:
        """Stage a prepared request after validating its same-store reservation."""

    def record_managed_queue_receipt(
        self, command_id: str, binding: Any, queue_receipt: Mapping[str, Any]
    ) -> Any:
        """Persist the exact local queue receipt on the staged row."""

    def dispatch_managed_command(self, command_id: str, binding: Any, sender: Any) -> Any:
        """Claim and dispatch one receipt-ready row, returning durable projection."""


@dataclass(frozen=True)
class CtpI9ManagedDispatchHandle:
    """A same-row SDK binding and its validated Store-facing echo."""

    binding: CtpManagedDispatchBinding
    source_binding: Any
    prepared: Any


def _scope_identity(scope: Any) -> Tuple[str, str, str]:
    provider = getattr(scope, "provider", None)
    account_key = getattr(scope, "account_key", None)
    scope_key = getattr(scope, "key", None)
    trading_day = getattr(scope, "trading_day", None)
    if (
        type(provider) is not str
        or provider.casefold() != "ctp"
        or type(account_key) is not str
        or not account_key.startswith("account:")
        or not _SHA256.fullmatch(account_key[8:])
        or type(scope_key) is not str
        or not scope_key.startswith("scope:")
        or not _SHA256.fullmatch(scope_key[6:])
        or type(trading_day) is not str
        or len(trading_day) != 8
        or not trading_day.isascii()
        or not trading_day.isdigit()
    ):
        raise ManagedExecutionAdapterError("I9 CTP execution scope is incomplete")
    try:
        date(int(trading_day[:4]), int(trading_day[4:6]), int(trading_day[6:8]))
    except ValueError as error:
        raise ManagedExecutionAdapterError("I9 CTP trading day is invalid") from error
    return account_key, scope_key, trading_day


def _reservation_values(value: Any) -> Tuple[str, str, str, str, str, str, int]:
    if isinstance(value, Mapping):
        raise ManagedExecutionAdapterError("I9 OrderRef reservation must be typed")
    names = (
        "account_key",
        "trading_day",
        "scope_key",
        "managed_intent_id",
        "runtime_order_id",
        "order_ref",
        "created_at_ns",
    )
    values = tuple(getattr(value, name, None) for name in names)
    if (
        any(type(item) is not str or not item for item in values[:6])
        or type(values[6]) is not int
        or values[6] <= 0
        or not values[0].startswith("account:")
        or not _SHA256.fullmatch(values[0][8:])
        or not values[2].startswith("scope:")
        or not _SHA256.fullmatch(values[2][6:])
        or len(values[1]) != 8
        or not values[1].isascii()
        or not values[1].isdigit()
        or not _RUNTIME_ID.fullmatch(values[4])
        or not _ORDER_REF.fullmatch(values[5])
    ):
        raise ManagedExecutionAdapterError("I9 OrderRef reservation is invalid")
    try:
        date(int(values[1][:4]), int(values[1][4:6]), int(values[1][6:8]))
    except ValueError as error:
        raise ManagedExecutionAdapterError("I9 OrderRef reservation day is invalid") from error
    return values  # type: ignore[return-value]


def _require_reservation(
    value: Any,
    *,
    scope: Any,
    managed_intent_id: str,
    runtime_order_id: str,
) -> Any:
    account_key, scope_key, trading_day = _scope_identity(scope)
    values = _reservation_values(value)
    if values != (
        account_key,
        trading_day,
        scope_key,
        managed_intent_id,
        runtime_order_id,
        values[5],
        values[6],
    ):
        raise ManagedExecutionAdapterError(
            "I9 OrderRef reservation account, day, scope, or intent conflicts"
        )
    return value


def _binding_from_i9(source_binding: Any) -> CtpManagedDispatchBinding:
    to_payload = getattr(source_binding, "to_payload", None)
    if not callable(to_payload):
        raise ManagedExecutionAdapterError("I9 dispatch binding has no typed payload")
    try:
        payload = to_payload()
    except Exception as error:
        raise ManagedExecutionAdapterError("I9 dispatch binding could not be read") from error
    return CtpManagedDispatchBinding.from_store_payload(payload)


def _assert_command_row_matches(
    row: Any,
    binding: CtpManagedDispatchBinding,
    *,
    post_dispatch: bool = False,
) -> None:
    if isinstance(row, Mapping):
        raise ManagedExecutionAdapterError("I9 durable command row must be typed")
    expected = {
        "account_key": binding.account_key,
        "scope_key": binding.scope_key,
        "trading_day": binding.trading_day,
        "operation": binding.operation.upper(),
        "command_id": binding.command_id,
        "request_payload": dict(binding.request_payload),
        "request_payload_sha256": binding.request_payload_sha256,
        "native_request_payload": dict(binding.native_request_payload),
        "native_request_payload_sha256": binding.native_request_payload_sha256,
        "reservation_managed_intent_id": binding.managed_intent_id,
        "order_ref": binding.order_ref if binding.operation == "submit" else None,
        "cancel_target_order_ref": (
            binding.cancel_target_order_ref if binding.operation == "cancel" else None
        ),
        "cancel_target_exchange_id": binding.cancel_target_exchange_id,
        "cancel_target_order_sys_id": binding.cancel_target_order_sys_id,
        "cancel_target_front_id": binding.cancel_target_front_id,
        "cancel_target_session_id": binding.cancel_target_session_id,
        "approval_use_id": binding.approval_use_id,
        "approval_digest": binding.approval_digest,
        "session_binding": dict(binding.session_binding),
        "session_binding_sha256": binding.session_binding_sha256,
        "local_queue_receipt_id": binding.local_queue_receipt_id,
        "local_queue_receipt_queued": binding.local_queue_receipt_queued,
    }
    if any(getattr(row, key, object()) != value for key, value in expected.items()):
        raise ManagedExecutionAdapterError("I9 durable command row differs from binding")
    if binding.local_queue_receipt_queued is None:
        allowed_statuses = {"READY"}
    elif binding.local_queue_receipt_queued is False:
        allowed_statuses = {"COMPLETED"}
    elif post_dispatch:
        allowed_statuses = {"READY", "CLAIMED", "COMPLETED", "UNKNOWN"}
    else:
        # The local receipt is committed before heap publication, so the
        # worker cannot have claimed this command while this callback runs.
        allowed_statuses = {"READY"}
    if getattr(row, "status", None) not in allowed_statuses:
        raise ManagedExecutionAdapterError("I9 durable command status differs from binding")
    correlation = getattr(row, "correlation_key", None)
    to_payload = getattr(correlation, "to_payload", None)
    if not callable(to_payload):
        raise ManagedExecutionAdapterError("I9 durable command lacks typed correlation")
    expected_correlation = {
        "version": 2,
        "account_key": binding.account_key,
        "scope_key": binding.scope_key,
        "trading_day": binding.trading_day,
        "operation": binding.operation.upper(),
        "command_id": binding.command_id,
        "request_payload_sha256": binding.request_payload_sha256,
        "reservation_managed_intent_id": binding.managed_intent_id,
        "managed_action_id": binding.managed_action_id,
        "runtime_order_id": binding.runtime_order_id,
        "order_ref": binding.order_ref,
        "cancel_target_exchange_id": binding.cancel_target_exchange_id,
        "cancel_target_order_sys_id": binding.cancel_target_order_sys_id,
        "cancel_target_front_id": binding.cancel_target_front_id,
        "cancel_target_session_id": binding.cancel_target_session_id,
        "approval_use_id": binding.approval_use_id,
        "approval_digest": binding.approval_digest,
        "session_binding_sha256": binding.session_binding_sha256,
        "session_generation_id": binding.session_generation_id,
        "dispatch_front_id": binding.dispatch_front_id,
        "dispatch_session_id": binding.dispatch_session_id,
        "native_request_id": binding.native_request_id,
        "native_action_ref": binding.native_action_ref,
        "native_request_payload_sha256": binding.native_request_payload_sha256,
    }
    if to_payload() != expected_correlation:
        raise ManagedExecutionAdapterError("I9 durable command correlation differs from binding")


def _validate_prepared(prepared: Any, reservation: Any, scope: Any) -> None:
    operation = getattr(prepared, "operation", None)
    if operation not in {"submit", "cancel"}:
        raise ManagedExecutionAdapterError("I9 prepared CTP operation is invalid")
    values = _reservation_values(reservation)
    intent_id = getattr(prepared, "managed_intent_id", None)
    runtime_order_id = getattr(prepared, "runtime_order_id", None)
    order_ref = getattr(prepared, "order_ref", None)
    if (values[3], values[4], values[5]) != (intent_id, runtime_order_id, order_ref):
        raise ManagedExecutionAdapterError("I9 prepared CTP identity differs from reservation")
    _require_reservation(
        reservation,
        scope=scope,
        managed_intent_id=intent_id,
        runtime_order_id=runtime_order_id,
    )
    cancel_id = getattr(prepared, "managed_cancel_intent_id", None)
    try:
        expected_command_id = ctp_managed_command_id(
            operation, intent_id, runtime_order_id, cancel_id
        )
    except ManagedExecutionAdapterError:
        raise
    if getattr(prepared, "command_id", None) != expected_command_id:
        raise ManagedExecutionAdapterError("I9 prepared CTP command key differs")
    receipt_id = getattr(prepared, "local_queue_receipt_id", None)
    if type(receipt_id) is not str or not _RECEIPT_ID.fullmatch(receipt_id):
        raise ManagedExecutionAdapterError("I9 prepared CTP queue receipt id is invalid")
    request = getattr(prepared, "request_payload", None)
    if not isinstance(request, Mapping) or request.get("OrderRef") != order_ref:
        raise ManagedExecutionAdapterError("I9 prepared CTP request does not echo OrderRef")
    if "OrderActionRef" in request or getattr(prepared, "native_action_ref", None) is not None:
        raise ManagedExecutionAdapterError(
            "I9 prepared logical request cannot contain Store-issued ActionRef"
        )
    session_binding = getattr(prepared, "session_binding", None)
    if not isinstance(session_binding, Mapping):
        raise ManagedExecutionAdapterError("I9 prepared CTP session binding is missing")
    expected_session = {
        "session_generation_id": getattr(prepared, "session_generation_id", None),
        "dispatch_front_id": getattr(prepared, "dispatch_front_id", None),
        "dispatch_session_id": getattr(prepared, "dispatch_session_id", None),
    }
    if any(session_binding.get(key) != value for key, value in expected_session.items()):
        raise ManagedExecutionAdapterError("I9 prepared CTP session binding differs")
    for value, name in (
        (getattr(prepared, "dispatch_front_id", None), "dispatch FrontID"),
        (getattr(prepared, "dispatch_session_id", None), "dispatch SessionID"),
        (getattr(prepared, "native_request_id", None), "native RequestID"),
    ):
        if type(value) is not int or not 1 <= value <= 2_147_483_647:
            raise ManagedExecutionAdapterError("I9 prepared CTP " + name + " is invalid")
    if operation == "submit":
        if cancel_id is not None or getattr(prepared, "native_action_ref", None) is not None:
            raise ManagedExecutionAdapterError("I9 submit binding contains cancel identity")
        return

    # This local I9 DTO currently requires the complete target tuple below.
    # The generic CTP TraderClient gate and SDK live Feed also support the
    # native alternatives ``OrderSysID + ExchangeID`` OR
    # ``OrderRef + FrontID + SessionID``. That means the current all-fields
    # contract excludes otherwise valid single-form native cancels. A future
    # trusted projection may model those alternatives as a discriminated
    # target and require any simultaneously supplied fields to agree with the
    # same verified order row. Do not relax this caller-input check before
    # that issuer exists; the managed native adapter currently requires the
    # full tuple as well.
    target = {
        "OrderRef": order_ref,
        "ExchangeID": getattr(prepared, "cancel_target_exchange_id", None),
        "OrderSysID": getattr(prepared, "cancel_target_order_sys_id", None),
        "FrontID": getattr(prepared, "cancel_target_front_id", None),
        "SessionID": getattr(prepared, "cancel_target_session_id", None),
    }
    if (
        type(cancel_id) is not str
        or not cancel_id
        or cancel_id == intent_id
        or any(value in (None, "") for value in target.values())
        or any(
            type(request.get(key)) is not type(value) or request.get(key) != value
            for key, value in target.items()
        )
        or type(prepared.cancel_target_front_id) is not int
        or not 1 <= prepared.cancel_target_front_id <= 2_147_483_647
        or type(prepared.cancel_target_session_id) is not int
        or not 1 <= prepared.cancel_target_session_id <= 2_147_483_647
        or type(prepared.cancel_target_exchange_id) is not str
        or not prepared.cancel_target_exchange_id.isascii()
        or not prepared.cancel_target_exchange_id.isalnum()
        or type(prepared.cancel_target_order_sys_id) is not str
        or not prepared.cancel_target_order_sys_id
        or not prepared.cancel_target_order_sys_id.isascii()
        or prepared.request_payload.get("ActionFlag") != "0"
        or type(prepared.request_payload.get("ActionFlag")) is not str
        or type(prepared.request_payload.get("LimitPrice")) not in (int, float)
        or prepared.request_payload.get("LimitPrice") != 0
        or type(prepared.request_payload.get("VolumeChange")) is not int
        or prepared.request_payload.get("VolumeChange") != 0
        or (
            "RequestID" in request
            and (
                type(request["RequestID"]) is not int
                or request["RequestID"] != prepared.native_request_id
            )
        )
    ):
        raise ManagedExecutionAdapterError("I9 cancel target does not match its exact binding")


def _require_binding_matches_prepared(
    binding: CtpManagedDispatchBinding, prepared: Any, reservation: Any, scope: Any
) -> None:
    reservation_values = _reservation_values(reservation)
    account_key, scope_key, trading_day = _scope_identity(scope)
    expected = {
        "operation": prepared.operation,
        "command_id": prepared.command_id,
        "account_key": account_key,
        "scope_key": scope_key,
        "trading_day": trading_day,
        "managed_intent_id": prepared.managed_intent_id,
        "runtime_order_id": prepared.runtime_order_id,
        "order_ref": prepared.order_ref,
        "request_payload": dict(prepared.request_payload),
        "request_payload_sha256": _managed_payload_sha256(
            prepared.request_payload, "request payload"
        ),
        "approval_use_id": prepared.approval_use_id,
        "approval_digest": prepared.approval_digest,
        "session_binding": dict(prepared.session_binding),
        "session_generation_id": prepared.session_generation_id,
        "dispatch_front_id": prepared.dispatch_front_id,
        "dispatch_session_id": prepared.dispatch_session_id,
        "native_request_id": prepared.native_request_id,
        "local_queue_receipt_id": prepared.local_queue_receipt_id,
        "order_ref_reservation_created_at_ns": reservation_values[6],
        "local_queue_receipt_queued": None,
    }
    if prepared.operation == "cancel":
        expected.update(
            managed_cancel_intent_id=prepared.managed_cancel_intent_id,
            managed_action_id=prepared.managed_cancel_intent_id,
            cancel_target_order_ref=prepared.order_ref,
            cancel_target_exchange_id=prepared.cancel_target_exchange_id,
            cancel_target_order_sys_id=prepared.cancel_target_order_sys_id,
            cancel_target_front_id=prepared.cancel_target_front_id,
            cancel_target_session_id=prepared.cancel_target_session_id,
            native_action_ref=binding.native_action_ref,
        )
    else:
        expected.update(
            managed_action_id=prepared.managed_intent_id,
            managed_cancel_intent_id=None,
            cancel_target_order_ref=None,
            cancel_target_exchange_id=None,
            cancel_target_order_sys_id=None,
            cancel_target_front_id=None,
            cancel_target_session_id=None,
            native_action_ref=None,
        )
    expected_native_payload = dict(prepared.request_payload)
    if prepared.operation == "cancel":
        expected_native_payload["OrderActionRef"] = binding.native_action_ref
    expected["native_request_payload"] = expected_native_payload
    expected["native_request_payload_sha256"] = _managed_payload_sha256(
        expected_native_payload, "native request payload"
    )
    if any(getattr(binding, key) != value for key, value in expected.items()):
        raise ManagedExecutionAdapterError("I9 dispatch binding differs from prepared reservation")


def _projection_from_i9(
    projection: Any, binding: CtpManagedDispatchBinding
) -> CtpManagedExecutionProjection:
    operation = "SUBMIT" if binding.operation == "submit" else "CANCEL"
    if (
        getattr(projection, "command_id", None) != binding.command_id
        or getattr(projection, "operation", None) != operation
        or getattr(projection, "local_queue_receipt_id", None) != binding.local_queue_receipt_id
        or getattr(projection, "local_queue_receipt_queued", None)
        is not binding.local_queue_receipt_queued
    ):
        raise ManagedExecutionAdapterError("I9 durable projection differs from dispatch binding")
    status = getattr(projection, "command_status", None)
    outcome = getattr(projection, "local_dispatch_outcome", None)
    queued = binding.local_queue_receipt_queued
    if queued is False:
        if status != "COMPLETED" or outcome != "REJECTED":
            raise ManagedExecutionAdapterError("I9 local queue rejection is not terminal")
        state = CtpManagedProjectionState.LOCAL_REJECTED
        error_code = "command_queue_rejected"
    elif queued is True:
        if (status == "READY" and outcome is None) or (
            status == "COMPLETED" and outcome == "QUEUED"
        ):
            state = CtpManagedProjectionState.PENDING
        elif status in {"CLAIMED", "UNKNOWN"} or outcome in {"UNKNOWN", "REJECTED"}:
            state = CtpManagedProjectionState.UNKNOWN
        else:
            raise ManagedExecutionAdapterError("I9 dispatch projection state is invalid")
        error_code = None
    else:
        raise ManagedExecutionAdapterError("I9 dispatch projection has no committed queue receipt")
    return CtpManagedExecutionProjection(
        operation=binding.operation,
        state=state,
        durable_projection_id=binding.command_id,
        managed_intent_id=binding.managed_intent_id,
        runtime_order_id=binding.runtime_order_id,
        managed_cancel_intent_id=binding.managed_cancel_intent_id,
        local_queue_receipt_id=binding.local_queue_receipt_id,
        error_code=error_code,
        dispatch_binding=binding,
        version=2,
    )


def _validate_store_queue_receipt(
    receipt: Any,
    *,
    operation: str,
    order_ref: str,
    receipt_id: str,
) -> bool:
    """Validate the Store receipt before making it durable in I9.

    The Store queue receipt is the last local fact available before the
    command is published to its worker. In particular, ``client_order_id``
    must echo the I9-reserved CTP OrderRef; accepting a Store-generated
    alternative here would reintroduce the second OrderRef allocator at the
    handoff boundary.
    """

    if not isinstance(receipt, Mapping):
        raise ManagedExecutionAdapterError("I9 Store queue receipt must be a mapping")
    queued = receipt.get("queued")
    if type(queued) is not bool:
        raise ManagedExecutionAdapterError("I9 Store queue receipt has no typed outcome")
    expected_command = "submit" if operation == "submit" else "cancel"
    expected_status = "submitted" if queued else "rejected"
    expected_priorities = {"open", "close"} if operation == "submit" else {"cancel"}
    if (
        receipt.get("kind") != "command_receipt"
        or receipt.get("command") != expected_command
        or receipt.get("receipt_id") != receipt_id
    ):
        raise ManagedExecutionAdapterError("I9 queue receipt differs from prepared binding")
    if receipt.get("client_order_id") != order_ref:
        raise ManagedExecutionAdapterError(
            "I9 Store client OrderRef differs from the durable reservation"
        )
    if receipt.get("status") != expected_status:
        raise ManagedExecutionAdapterError("I9 Store queue receipt status conflicts with outcome")
    if receipt.get("priority") not in expected_priorities:
        raise ManagedExecutionAdapterError("I9 Store queue receipt priority is invalid")
    queue_depth = receipt.get("queue_depth")
    if type(queue_depth) is not int or queue_depth < 0 or (queued and queue_depth == 0):
        raise ManagedExecutionAdapterError("I9 Store queue receipt depth is invalid")
    if queued:
        if receipt.get("error_code") not in (None, "") or receipt.get("error_msg") not in (
            None,
            "",
        ):
            raise ManagedExecutionAdapterError(
                "I9 accepted Store queue receipt contains rejection details"
            )
    elif (
        type(receipt.get("error_code")) is not str
        or not receipt["error_code"]
        or type(receipt.get("error_msg")) is not str
        or not receipt["error_msg"]
    ):
        raise ManagedExecutionAdapterError(
            "I9 rejected Store queue receipt lacks rejection details"
        )
    return queued


class CtpI9ManagedDispatchBridge:
    """Bind I9's exclusive OrderRef row and single worker to the Store DTO.

    Exact installed I9 types and same-object store wiring are required before
    any reservation or worker method runs. Fake structural ports cannot enable
    this bridge. Local I9 projections never establish provider order state.

    A cancel source must be stronger than the caller-supplied target fields in
    ``CtpManagedPreparedDispatch``. I9's reservation binds account key, scope
    key, trading day, intent, runtime order ID, and OrderRef, but has no
    instrument, provider account fingerprint, or provider session identity.
    The current CTP query verifier can validate a native order snapshot against
    its own account, day, connection generation, and registration, but its
    result is not joined to that I9 reservation. A ``CtpSimulationOrderSnapshot``
    or local I9 dispatch projection by itself therefore cannot authorize a
    cancel.

    The minimum future projection port must return one immutable, verifier-
    issued current-order projection selected by the reserved OrderRef, and
    bind it to the exact I9 reservation plus a code-owned I9-to-CTP scope
    receipt. That receipt must join I9 account/scope/day to the verified CTP
    account fingerprint, trading day, registration digest, instrument and
    exchange, and session generation. The query provenance must retain its
    native request identity, exact filters, terminal/current-result evidence,
    and record digest. The returned native row must be uniquely OPEN or
    PARTIAL and expose the exact target identity (OrderSysID, or OrderRef plus
    FrontID and SessionID). This bridge has no such trusted issuer today, so
    cancel staging and queue callbacks stay closed.
    """

    def __init__(self, *, scope: Any, identity_port: Any, single_worker: Any) -> None:
        _scope_identity(scope)
        if any(
            not callable(getattr(identity_port, name, None))
            for name in (
                "reserve_ctp_order_identity",
                "read_ctp_order_identity",
                "read_ctp_dispatch_command",
                "read_ctp_dispatch_projection",
            )
        ):
            raise ManagedExecutionAdapterError(
                "I9 CTP reservation and same-store readback authority is unavailable"
            )
        if any(
            not callable(getattr(single_worker, name, None))
            for name in (
                "stage_prepared_dispatch",
                "record_managed_queue_receipt",
                "dispatch_managed_command",
            )
        ):
            raise ManagedExecutionAdapterError("I9 single-worker dispatch port is incomplete")
        self._scope = scope
        self._identity_port = identity_port
        self._single_worker = single_worker
        self._issued_handles = []

    def _require_same_store_authority(self) -> Tuple[type, ...]:
        """Reject structural/fake ports before any reserve, stage, or dispatch.

        The reviewed I9 worker does not yet publish an opaque authority token,
        so activation is limited to its exact installed classes and object
        identity between ``worker._store`` and ``identity_port``. The private
        attribute check is deliberately narrow and version-sensitive: if I9
        changes it or runs below Python 3.11, the bridge refuses to operate.
        """

        types = _trusted_i9_types()
        if types is None:
            raise ManagedExecutionAdapterError(
                "trusted I9 same-store binding is unavailable; bridge is non-authorizing"
            )
        scope_type, store_type, _, worker_type, _, _, _, _ = types
        if (
            type(self._scope) is not scope_type
            or type(self._identity_port) is not store_type
            or type(self._single_worker) is not worker_type
            or getattr(self._single_worker, "_store", None) is not self._identity_port
            or type(getattr(self._single_worker, "_scope", None)) is not scope_type
            or getattr(self._single_worker, "_scope", None) != self._scope
        ):
            raise ManagedExecutionAdapterError(
                "trusted I9 same-store binding requires the exact store, worker, and scope"
            )
        return types

    def reserve_submit_order_identity(self, managed_intent_id: str, runtime_order_id: str) -> Any:
        """Allocate one submit OrderRef only through I9, then verify readback."""

        trusted_types = self._require_same_store_authority()
        reservation_type = trusted_types[2]
        try:
            reserved = self._identity_port.reserve_ctp_order_identity(
                self._scope, managed_intent_id, runtime_order_id
            )
            current = self._identity_port.read_ctp_order_identity(self._scope, managed_intent_id)
        except Exception as error:
            raise ManagedExecutionAdapterError("I9 OrderRef reservation failed") from error
        if (
            type(reserved) is not reservation_type
            or current is None
            or type(current) is not reservation_type
        ):
            raise ManagedExecutionAdapterError("I9 OrderRef reservation readback is missing")
        _require_reservation(
            reserved,
            scope=self._scope,
            managed_intent_id=managed_intent_id,
            runtime_order_id=runtime_order_id,
        )
        _require_reservation(
            current,
            scope=self._scope,
            managed_intent_id=managed_intent_id,
            runtime_order_id=runtime_order_id,
        )
        if _reservation_values(reserved) != _reservation_values(current):
            raise ManagedExecutionAdapterError("I9 OrderRef reservation readback conflicts")
        return reserved

    def read_cancel_order_identity(
        self,
        managed_intent_id: str,
        runtime_order_id: str,
        expected_order_ref: str,
    ) -> Any:
        """Read, never allocate, the target order's I9 OrderRef reservation."""

        reservation_type = self._require_same_store_authority()[2]
        try:
            reservation = self._identity_port.read_ctp_order_identity(
                self._scope, managed_intent_id
            )
        except Exception as error:
            raise ManagedExecutionAdapterError("I9 cancel OrderRef readback failed") from error
        if reservation is None or type(reservation) is not reservation_type:
            raise ManagedExecutionAdapterError("I9 cancel target has no OrderRef reservation")
        _require_reservation(
            reservation,
            scope=self._scope,
            managed_intent_id=managed_intent_id,
            runtime_order_id=runtime_order_id,
        )
        if _reservation_values(reservation)[5] != expected_order_ref:
            raise ManagedExecutionAdapterError("I9 cancel target OrderRef conflicts")
        return reservation

    def stage_prepared_dispatch(self, prepared: Any) -> CtpI9ManagedDispatchHandle:
        """Stage using I9's candidate and validate its binding against I9 readback."""

        trusted_types = self._require_same_store_authority()
        prepared_type = trusted_types[4]
        reservation_type = trusted_types[2]
        if type(prepared) is not prepared_type:
            raise ManagedExecutionAdapterError("typed I9 prepared dispatch is required")
        intent_id = getattr(prepared, "managed_intent_id", None)
        runtime_order_id = getattr(prepared, "runtime_order_id", None)
        try:
            reservation = self._identity_port.read_ctp_order_identity(self._scope, intent_id)
        except Exception as error:
            raise ManagedExecutionAdapterError("I9 prepared reservation read failed") from error
        if reservation is None or type(reservation) is not reservation_type:
            raise ManagedExecutionAdapterError("I9 prepared dispatch has no reserved OrderRef")
        _validate_prepared(prepared, reservation, self._scope)
        _require_reservation(
            reservation,
            scope=self._scope,
            managed_intent_id=intent_id,
            runtime_order_id=runtime_order_id,
        )
        if prepared.operation == "cancel":
            # Validate supplied echoes, but they are caller-provided. The
            # bridge has no issuer that joins native query evidence to this
            # exact I9 reservation and provider session.
            raise ManagedExecutionAdapterError(
                "I9 cancel target lacks trusted typed order-projection provenance"
            )
        try:
            source_binding = self._single_worker.stage_prepared_dispatch(prepared)
            if type(source_binding) is not trusted_types[5]:
                raise ManagedExecutionAdapterError("I9 worker returned an untyped binding")
            binding = _binding_from_i9(source_binding)
            command_row = self._identity_port.read_ctp_dispatch_command(
                self._scope, binding.command_id
            )
            if type(command_row) is not trusted_types[7]:
                raise ManagedExecutionAdapterError("I9 command readback is not typed")
        except Exception as error:
            raise ManagedExecutionAdapterError(
                "I9 dispatch staging rejected the binding"
            ) from error
        _require_binding_matches_prepared(binding, prepared, reservation, self._scope)
        _assert_command_row_matches(command_row, binding)
        handle = CtpI9ManagedDispatchHandle(binding, source_binding, prepared)
        self._issued_handles.append(handle)
        return handle

    def read_projection(self, binding: CtpManagedDispatchBinding) -> CtpManagedExecutionProjection:
        """Read local outbox state; this is never provider-order provenance."""

        trusted_types = self._require_same_store_authority()
        projection_type = trusted_types[6]
        if type(binding) is not CtpManagedDispatchBinding:
            raise ManagedExecutionAdapterError("typed I9 Store binding is required")
        try:
            command_row = self._identity_port.read_ctp_dispatch_command(
                self._scope, binding.command_id
            )
            projection = self._identity_port.read_ctp_dispatch_projection(
                self._scope, binding.command_id
            )
        except Exception as error:
            raise ManagedExecutionAdapterError("I9 durable projection read failed") from error
        if type(command_row) is not trusted_types[7]:
            raise ManagedExecutionAdapterError("I9 command readback is not typed")
        _assert_command_row_matches(command_row, binding, post_dispatch=True)
        if projection is None or type(projection) is not projection_type:
            raise ManagedExecutionAdapterError("I9 durable projection is missing")
        return _projection_from_i9(projection, binding)

    def queue_ports(
        self,
        handle: CtpI9ManagedDispatchHandle,
        *,
        sender: Callable[[Any], Any],
    ) -> Tuple[Callable[[Mapping[str, Any]], CtpManagedDispatchBinding], Callable[..., Any]]:
        """Return receipt-writer and typed dispatcher callbacks for Store enqueue."""

        self._require_same_store_authority()
        if type(handle) is not CtpI9ManagedDispatchHandle or not callable(sender):
            raise ManagedExecutionAdapterError("I9 Store queue callbacks are invalid")
        if not any(issued is handle for issued in self._issued_handles):
            raise ManagedExecutionAdapterError(
                "I9 queue callbacks require a handle issued by this bridge instance"
            )
        if handle.binding.operation != "submit" or handle.prepared.operation != "submit":
            raise ManagedExecutionAdapterError(
                "I9 cancel queue callbacks require trusted provider order-projection provenance"
            )
        current_source = handle.source_binding
        current_binding = handle.binding
        if current_binding.local_queue_receipt_queued is not None:
            raise ManagedExecutionAdapterError("I9 staged binding already has a queue receipt")

        def persist_receipt(receipt: Mapping[str, Any]) -> CtpManagedDispatchBinding:
            nonlocal current_source, current_binding
            trusted_types = self._require_same_store_authority()
            queued = _validate_store_queue_receipt(
                receipt,
                operation=current_binding.operation,
                order_ref=current_binding.order_ref,
                receipt_id=current_binding.local_queue_receipt_id,
            )
            try:
                recorded = self._single_worker.record_managed_queue_receipt(
                    current_binding.command_id,
                    current_source,
                    receipt,
                )
                if type(recorded) is not trusted_types[5]:
                    raise ManagedExecutionAdapterError(
                        "I9 receipt writer returned an untyped binding"
                    )
                recorded_store_binding = _binding_from_i9(recorded)
            except Exception as error:
                raise ManagedExecutionAdapterError(
                    "I9 queue receipt could not be committed before publication"
                ) from error
            expected = replace(current_binding, local_queue_receipt_queued=queued)
            if recorded_store_binding != expected:
                raise ManagedExecutionAdapterError("I9 committed queue receipt binding differs")
            try:
                command_row = self._identity_port.read_ctp_dispatch_command(
                    self._scope, current_binding.command_id
                )
            except Exception as error:
                raise ManagedExecutionAdapterError("I9 receipt row readback failed") from error
            if type(command_row) is not trusted_types[7]:
                raise ManagedExecutionAdapterError("I9 receipt row readback is not typed")
            _assert_command_row_matches(command_row, recorded_store_binding)
            current_source = recorded
            current_binding = recorded_store_binding
            return current_binding

        async def dispatch(
            store_binding: CtpManagedDispatchBinding,
        ) -> CtpManagedExecutionProjection:
            trusted_types = self._require_same_store_authority()
            if (
                type(store_binding) is not CtpManagedDispatchBinding
                or store_binding != current_binding
                or store_binding.local_queue_receipt_queued is not True
            ):
                raise ManagedExecutionAdapterError("I9 dispatch requires the receipt-ready binding")
            result = self._single_worker.dispatch_managed_command(
                store_binding.command_id,
                current_source,
                sender,
            )
            if inspect.isawaitable(result):
                result = await result
            try:
                command_row = self._identity_port.read_ctp_dispatch_command(
                    self._scope, store_binding.command_id
                )
                persisted = self._identity_port.read_ctp_dispatch_projection(
                    self._scope, store_binding.command_id
                )
            except Exception as error:
                raise ManagedExecutionAdapterError(
                    "I9 post-dispatch projection read failed"
                ) from error
            if type(command_row) is not trusted_types[7]:
                raise ManagedExecutionAdapterError("I9 post-dispatch command row is not typed")
            _assert_command_row_matches(command_row, store_binding, post_dispatch=True)
            if (
                type(result) is not trusted_types[6]
                or type(persisted) is not trusted_types[6]
                or persisted != result
            ):
                raise ManagedExecutionAdapterError(
                    "I9 worker result differs from same-store durable projection"
                )
            return _projection_from_i9(persisted, store_binding)

        return persist_receipt, dispatch


__all__ = [
    "CtpI9ManagedDispatchBridge",
    "CtpI9ManagedDispatchHandle",
    "CtpI9OrderIdentityPort",
    "CtpI9SingleWorkerPort",
]
