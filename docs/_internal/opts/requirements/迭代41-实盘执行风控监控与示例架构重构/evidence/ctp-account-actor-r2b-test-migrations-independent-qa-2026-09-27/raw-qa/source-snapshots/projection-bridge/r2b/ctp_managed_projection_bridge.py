"""Bridge an authoritative CTP SDK outbox into Backtrader projections.

The Store's CTP path queues SDK commands and requires a typed projection
readback.  This adapter only joins those two ports; it never calls a native
CTP client itself.  Its authority must provide a durable, single-writer
outbox that reserves a command before the SDK queue callback and reads the
projection back from that same outbox.

``CtpSimulationExecutionSession`` is not such an authority today.  Its
``submit_order``/``cancel_order`` methods synchronously dispatch to
``CtpSimulationNativePort`` and return state strings, while its journal has
private read methods and no Store command key or projection DTO.  Passing it
here therefore fails during construction, before the Store can queue or send
anything.  A future ``bt_api_execution`` adapter can implement the port below
and become the sole write authority without adding a parallel native path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .managed_execution import (
    CtpManagedCancelDispatch,
    CtpManagedExecutionProjection,
    CtpManagedOrderDispatch,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    require_ctp_managed_execution_projection,
)


class CtpManagedProjectionAuthorityError(ManagedExecutionAdapterError):
    """The outbox could not prove a projection after an ambiguous handoff."""

    def __init__(self, code: str = "managed_ctp_projection_unknown") -> None:
        super().__init__("managed CTP outbox projection is unavailable; outcome is UNKNOWN")
        self.code = code
        self.execution_unknown = True
        self.managed_execution_state = "UNKNOWN"
        self.managed_projection_pending = True
        self.managed_unknown = True


@dataclass(frozen=True)
class CtpManagedOutboxReservation:
    """Result of an atomic durable reservation for one stable command key.

    Exactly one caller may receive ``dispatch_claimed=True`` for a command
    key.  A replay returns the existing projection with no dispatch claim.
    A concurrent or unresolved reservation may return neither; the adapter
    then reads the row and preserves UNKNOWN if it still cannot be proved.
    """

    command_id: str
    dispatch_claimed: bool
    projection: Optional[CtpManagedExecutionProjection] = None

    def __post_init__(self) -> None:
        if (
            type(self.command_id) is not str
            or len(self.command_id) != len("ctp-outbox-v1:") + 64
            or not self.command_id.startswith("ctp-outbox-v1:")
            or any(character not in "0123456789abcdef" for character in self.command_id[14:])
        ):
            raise ManagedExecutionAdapterError("managed CTP outbox command id is invalid")
        if type(self.dispatch_claimed) is not bool:
            raise ManagedExecutionAdapterError("managed CTP outbox dispatch claim is invalid")
        if self.projection is not None and type(self.projection) is not CtpManagedExecutionProjection:
            raise ManagedExecutionAdapterError("managed CTP outbox replay projection is untyped")
        if self.dispatch_claimed and self.projection is not None:
            raise ManagedExecutionAdapterError(
                "managed CTP outbox cannot claim dispatch for an existing projection"
            )


class CtpManagedExecutionOutboxPort(Protocol):
    """Single-authority journal contract required by the Store adapter.

    Implementations must commit ``reserve_managed_dispatch`` before allowing
    the callback to reach the Store's SDK queue.  The command key is
    ``ctp-outbox-v1:`` plus SHA-256 of the ASCII fields joined by NUL:
    ``backtrader.ctp.managed-outbox.v1``, operation, managed intent ID,
    runtime order ID, and cancel intent ID (empty for submit).  The SDK can
    derive that same key from the typed identity already carried in its queued
    request; Backtrader order refs and local receipt IDs are not command keys.
    The key and complete canonical request digest must be bound to one row.
    A crash or uncertain callback outcome must become durable UNKNOWN and must
    never be retried. ``read_managed_projection`` must return a DTO derived
    from that row, not a synthesized response or provider ACK. Its
    ``durable_projection_id`` must equal ``command_id`` and its echoed
    operation, intent, runtime order and optional cancel identities must match
    the reserved row. The exact Store/Broker DTO is
    ``CtpManagedExecutionProjection.to_store_response()``: PENDING and UNKNOWN
    keep orders alive, and neither state can carry a provider ID, ACK, or fill.
    """

    def reserve_managed_dispatch(
        self,
        *,
        command_id: str,
        operation: str,
        identity: Any,
    ) -> CtpManagedOutboxReservation:
        """Atomically reserve the command and grant at most one dispatch claim."""

    def record_managed_queue_receipt(
        self,
        *,
        command_id: str,
        operation: str,
        identity: Any,
        queue_receipt: Mapping[str, Any],
    ) -> None:
        """Persist the exact local receipt; it is not provider acceptance."""

    def mark_managed_unknown(
        self,
        *,
        command_id: str,
        operation: str,
        identity: Any,
        queue_receipt: Optional[Mapping[str, Any]],
        reason: str,
    ) -> None:
        """Durably freeze an ambiguous command without making it retryable."""

    def read_managed_projection(
        self, *, command_id: str
    ) -> Optional[CtpManagedExecutionProjection]:
        """Read a typed projection from the reserved outbox row."""


def require_ctp_managed_execution_outbox_port(value: Any) -> CtpManagedExecutionOutboxPort:
    """Reject sessions that lack the one-row reservation/readback contract."""

    required = (
        "reserve_managed_dispatch",
        "record_managed_queue_receipt",
        "mark_managed_unknown",
        "read_managed_projection",
    )
    if any(not callable(getattr(value, name, None)) for name in required):
        raise ManagedExecutionAdapterError(
            "managed CTP authority lacks the durable Store outbox projection port"
        )
    return value


def _stable_command_id(operation: str, identity: Any) -> str:
    cancel_id = getattr(identity, "managed_cancel_intent_id", None) or ""
    material = "\0".join(
        (
            "backtrader.ctp.managed-outbox.v1",
            operation,
            identity.managed_intent_id,
            identity.runtime_order_id,
            cancel_id,
        )
    )
    return "ctp-outbox-v1:" + hashlib.sha256(material.encode("ascii")).hexdigest()


class CtpManagedExecutionProjectionAdapter:
    """Adapt one SDK outbox authority to ``BtApiStore``'s typed CTP port.

    The authority is responsible for durable reservation, dispatch outcome
    persistence, recovery, and account/write freezes.  The Store callback is
    the only dispatch path exposed here.  The adapter calls it at most once
    after a new reservation and always reads the final DTO back by the stable
    outbox command ID.
    """

    ctp_managed_execution_version = 1

    def __init__(self, runtime: Any, *, authority: Any, hedge_flag: str) -> None:
        self.runtime = runtime
        self.authority = require_ctp_managed_execution_outbox_port(authority)
        self.hedge_flag = hedge_flag
        if type(hedge_flag) is not str or hedge_flag not in ("1", "2", "3"):
            raise ManagedExecutionAdapterError("managed CTP hedge_flag is invalid")

    @staticmethod
    def _info(order: Any, name: str) -> Any:
        info = getattr(order, "info", None)
        getter = getattr(info, "get", None)
        return getter(name) if callable(getter) else None

    def _identity(self, order: Any, *, cancel: bool = False) -> Any:
        # Import runtime validation lazily: merely importing the Store bridge
        # must not load any provider, SDK, or execution capability.
        from backtrader_runtime.managed_execution import (
            _managed_runtime_order_id,
            strict_limit_intent_from_order,
        )

        intent_id = self._info(order, "managed_intent_id")
        if type(intent_id) is not str or not intent_id or intent_id != intent_id.strip():
            raise ManagedExecutionAdapterError("managed CTP intent identity is invalid")
        runtime_order_id = _managed_runtime_order_id(self.runtime.scope, intent_id)
        declared_runtime_id = self._info(order, "runtime_order_id")
        if declared_runtime_id not in (None, "", runtime_order_id):
            raise ManagedExecutionAdapterError("managed CTP runtime order identity mismatch")
        if cancel:
            cancel_id = self._info(order, "managed_cancel_intent_id") or "cancel." + intent_id
            return CtpManagedCancelDispatch(
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                managed_cancel_intent_id=cancel_id,
            )

        # Validate the actual Backtrader order against the runtime's approved
        # strict limit-order mapping before reserving anything in the outbox.
        strict_limit_intent_from_order(order, self.runtime)
        return CtpManagedOrderDispatch(
            order=order,
            managed_intent_id=intent_id,
            runtime_order_id=runtime_order_id,
            hedge_flag=self.hedge_flag,
        )

    def _unknown_projection(
        self,
        operation: str,
        command_id: str,
        identity: Any,
        queue_receipt: Optional[Mapping[str, Any]],
        reason: str,
        cause: Optional[BaseException] = None,
    ) -> CtpManagedExecutionProjection:
        try:
            self.authority.mark_managed_unknown(
                command_id=command_id,
                operation=operation,
                identity=identity,
                queue_receipt=queue_receipt,
                reason=reason,
            )
            projection = self.authority.read_managed_projection(command_id=command_id)
            return self._validate_projection(
                projection,
                operation=operation,
                identity=identity,
                queue_receipt=queue_receipt,
                require_unknown=True,
            )
        except Exception as error:
            unknown = CtpManagedProjectionAuthorityError()
            if cause is not None:
                raise unknown from cause
            raise unknown from error

    def _validate_projection(
        self,
        projection: Any,
        *,
        operation: str,
        identity: Any,
        queue_receipt: Optional[Mapping[str, Any]],
        require_unknown: bool = False,
    ) -> CtpManagedExecutionProjection:
        if type(projection) is not CtpManagedExecutionProjection:
            raise ManagedExecutionAdapterError("managed CTP outbox projection is missing or untyped")
        if projection.durable_projection_id != _stable_command_id(operation, identity):
            raise ManagedExecutionAdapterError("managed CTP projection command key does not match")
        projection = require_ctp_managed_execution_projection(
            projection,
            operation=operation,
            managed_intent_id=identity.managed_intent_id,
            runtime_order_id=identity.runtime_order_id,
            managed_cancel_intent_id=getattr(identity, "managed_cancel_intent_id", None),
            local_queue_receipt=queue_receipt,
        )
        if require_unknown and projection.state is not CtpManagedProjectionState.UNKNOWN:
            raise ManagedExecutionAdapterError("managed CTP outbox did not persist UNKNOWN")
        return projection

    @staticmethod
    def _validate_reservation(
        reservation: Any,
        command_id: str,
    ) -> CtpManagedOutboxReservation:
        if type(reservation) is not CtpManagedOutboxReservation:
            raise ManagedExecutionAdapterError("managed CTP outbox reservation is untyped")
        if reservation.command_id != command_id:
            raise ManagedExecutionAdapterError("managed CTP outbox reservation key differs")
        return reservation

    def _dispatch_or_replay(
        self,
        operation: str,
        identity: Any,
        sdk_dispatch: Callable[[Any], Any],
        *,
        order: Any,
    ) -> CtpManagedExecutionProjection:
        from backtrader_runtime.managed_execution import classify_ctp_queue_receipt

        command_id = _stable_command_id(operation, identity)
        queue_receipt: Optional[Mapping[str, Any]] = None
        try:
            reservation = self._validate_reservation(
                self.authority.reserve_managed_dispatch(
                    command_id=command_id,
                    operation=operation,
                    identity=identity,
                ),
                command_id,
            )
            if reservation.projection is not None:
                return self._validate_projection(
                    reservation.projection,
                    operation=operation,
                    identity=identity,
                    queue_receipt=None,
                )
            if not reservation.dispatch_claimed:
                projection = self.authority.read_managed_projection(command_id=command_id)
                if projection is None:
                    return self._unknown_projection(
                        operation,
                        command_id,
                        identity,
                        None,
                        "outbox_reservation_unresolved",
                    )
                return self._validate_projection(
                    projection,
                    operation=operation,
                    identity=identity,
                    queue_receipt=None,
                )

            # This is the only Store/SDK queue call for a newly claimed command.
            receipt = sdk_dispatch(identity)
            if not isinstance(receipt, Mapping):
                return self._unknown_projection(
                    operation,
                    command_id,
                    identity,
                    None,
                    "store_queue_receipt_missing",
                )
            queue_receipt = receipt
            expected_bt_order_ref = (
                None
                if operation == "cancel" and receipt.get("bt_order_ref") is None
                else getattr(order, "ref", None)
            )
            classify_ctp_queue_receipt(
                receipt,
                operation=operation,
                expected_bt_order_ref=expected_bt_order_ref,
                expected_client_order_id=self._info(order, "client_order_id"),
            )
            self.authority.record_managed_queue_receipt(
                command_id=command_id,
                operation=operation,
                identity=identity,
                queue_receipt=receipt,
            )
            projection = self.authority.read_managed_projection(command_id=command_id)
            return self._validate_projection(
                projection,
                operation=operation,
                identity=identity,
                queue_receipt=receipt,
            )
        except Exception as error:
            return self._unknown_projection(
                operation,
                command_id,
                identity,
                queue_receipt,
                "outbox_dispatch_or_projection_failed",
                error,
            )

    def submit_order(self, order: Any, sdk_dispatch: Callable[[Any], Any]) -> Any:
        try:
            identity = self._identity(order)
        except Exception as error:
            # No queue callback was given a chance to run. The Store will
            # classify this as a local managed rejection.
            setattr(error, "managed_local_reject", True)
            raise
        return self._dispatch_or_replay("submit", identity, sdk_dispatch, order=order)

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        sdk_dispatch: Callable[[Any], Any],
    ) -> Any:
        try:
            identity = self._identity(order_or_ref, cancel=True)
        except Exception as error:
            setattr(error, "managed_local_reject", True)
            raise
        return self._dispatch_or_replay(
            "cancel", identity, sdk_dispatch, order=order_or_ref
        )


__all__ = [
    "CtpManagedExecutionOutboxPort",
    "CtpManagedExecutionProjectionAdapter",
    "CtpManagedOutboxReservation",
    "CtpManagedProjectionAuthorityError",
    "require_ctp_managed_execution_outbox_port",
]
