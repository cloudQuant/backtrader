"""Read one exact durable CTP command projection on the caller's main thread.

This is a pure, non-authorizing reducer. A reviewed runtime composition must
supply both the reader and the exact sealed scope used to read one command.
The reducer does not authenticate a caller-supplied projection, import the SDK,
change Broker state, or dispatch provider work. A local ``QUEUED`` result never
becomes a Backtrader acknowledgement. Submit order state, cancel-action state,
and cancel target-order state remain separate facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .ctp_managed_cancel_binding import (
    CtpManagedCancelActionBindingV1,
    CtpManagedCancelTargetV1,
)


class CtpDispatchReadModelError(ValueError):
    """An exact command projection is absent, malformed, or mismatched."""


_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUNTIME_ORDER_ID_RE = re.compile(r"^bt-managed-v1:[0-9a-f]{64}$")
_ORDER_REF_RE = re.compile(r"^[0-9]{12}$")
_ORDER_STATES = frozenset({"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"})
_ORDER_TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED"})
_CANCEL_ACTION_STATES = frozenset({"ACKNOWLEDGED", "REJECTED", "TERMINAL"})
_CANCEL_ACTION_TERMINAL_STATES = frozenset({"REJECTED", "TERMINAL"})


@dataclass(frozen=True)
class CtpDispatchReadExpectation:
    """The one staged action whose read model a reviewed caller expects.

    ``managed_intent_id``, ``runtime_order_id``, and ``order_ref`` come from
    the exact sealed command binding. A cancel additionally requires the
    complete independently typed cancel binding, including ExchangeID.
    """

    command_id: str
    operation: str
    managed_intent_id: str
    runtime_order_id: str
    order_ref: str
    cancel_binding: Optional[CtpManagedCancelActionBindingV1] = None

    def __post_init__(self) -> None:
        _identity(self.command_id, "command_id")
        if type(self.operation) is not str or self.operation not in {"SUBMIT", "CANCEL"}:
            raise CtpDispatchReadModelError("invalid expected CTP operation")
        _identity(self.managed_intent_id, "managed_intent_id")
        if type(self.runtime_order_id) is not str or not _RUNTIME_ORDER_ID_RE.fullmatch(
            self.runtime_order_id
        ):
            raise CtpDispatchReadModelError("invalid expected CTP runtime_order_id")
        if type(self.order_ref) is not str or not _ORDER_REF_RE.fullmatch(self.order_ref):
            raise CtpDispatchReadModelError("invalid expected CTP OrderRef")

        if self.operation == "SUBMIT":
            if self.cancel_binding is not None:
                raise CtpDispatchReadModelError("submit expectation cannot carry a cancel binding")
            return

        if type(self.cancel_binding) is not CtpManagedCancelActionBindingV1:
            raise CtpDispatchReadModelError("typed exact CTP cancel binding is required")
        if (
            self.cancel_binding.managed_action_id == self.managed_intent_id
            or type(self.cancel_binding.target) is not CtpManagedCancelTargetV1
            or self.cancel_binding.target.order_ref != self.order_ref
        ):
            raise CtpDispatchReadModelError("expected CTP cancel binding identity is invalid")


@dataclass(frozen=True)
class CtpManagedDispatchReadModel:
    """Read-only local and provider facts for one exact CTP command.

    ``action_requires_write_freeze`` is an advisory contract signal for this
    command when it is still CLAIMED or has unresolved UNKNOWN dispatch. It is
    not a global writer-fence result, does not itself freeze a live account,
    and never grants permission when false. The model deliberately contains no
    Backtrader status, fill, accepted flag, or provider-observation object.
    """

    command_id: str
    operation: str
    command_status: str
    local_dispatch_outcome: Optional[str]
    managed_intent_id: str
    runtime_order_id: str
    order_ref: str
    cancel_action_id: Optional[str]
    cancel_target: Optional[CtpManagedCancelTargetV1]
    provider_order_state: Optional[str]
    provider_order_source_kind: Optional[str]
    cancel_action_state: Optional[str]
    cancel_action_source_kind: Optional[str]
    target_order_state: Optional[str]
    target_order_source_kind: Optional[str]
    unknown_resolution_order_state: Optional[str]
    unknown_resolution_cancel_action_state: Optional[str]
    action_requires_write_freeze: bool


class CtpDispatchProjectionReader(Protocol):
    """Read-only port supplied by a reviewed composition for one exact scope."""

    def read_ctp_dispatch_projection(self, scope: Any, command_id: str) -> Any:
        """Return the durable projection for this exact scope and command."""


def read_ctp_managed_dispatch_model(
    reader: CtpDispatchProjectionReader,
    sealed_scope: Any,
    expected: CtpDispatchReadExpectation,
) -> Optional[CtpManagedDispatchReadModel]:
    """Read and reduce one command without rebuilding or widening its scope.

    Call this only from the Backtrader main thread. ``sealed_scope`` is passed
    to the supplied reader unchanged. The reader/source must come from a
    reviewed runtime composition; this function does not prove that property
    or authenticate a projection object supplied by another caller. A missing
    row returns ``None`` so callers cannot infer acceptance from absence.
    """

    if type(expected) is not CtpDispatchReadExpectation:
        raise CtpDispatchReadModelError("typed exact CTP command expectation is required")
    if sealed_scope is None:
        raise CtpDispatchReadModelError("exact sealed CTP scope is required")
    read = getattr(reader, "read_ctp_dispatch_projection", None)
    if not callable(read):
        raise CtpDispatchReadModelError("durable CTP projection reader is unavailable")
    projection = read(sealed_scope, expected.command_id)
    if projection is None:
        return None
    return reduce_ctp_managed_dispatch_projection(projection, expected)


def reduce_ctp_managed_dispatch_projection(
    projection: Any,
    expected: CtpDispatchReadExpectation,
) -> CtpManagedDispatchReadModel:
    """Reduce one typed-shaped durable projection into distinct local/provider facts.

    This reducer is intentionally structural and non-authorizing. Its caller
    must obtain ``projection`` from the reviewed read-only source described by
    :func:`read_ctp_managed_dispatch_model`; constructing a lookalike value is
    not evidence of a verified callback.
    """

    if type(expected) is not CtpDispatchReadExpectation:
        raise CtpDispatchReadModelError("typed exact CTP command expectation is required")
    if projection is None:
        raise CtpDispatchReadModelError("CTP command projection is missing")

    command_id = _field(projection, "command_id")
    operation = _field(projection, "operation")
    command_status = _field(projection, "command_status")
    local_outcome = _field(projection, "local_dispatch_outcome")
    if command_id != expected.command_id or operation != expected.operation:
        raise CtpDispatchReadModelError("CTP command projection identity does not match")
    if type(command_status) is not str or command_status not in {
        "READY",
        "CLAIMED",
        "COMPLETED",
        "UNKNOWN",
    }:
        raise CtpDispatchReadModelError("invalid CTP command status")
    _validate_local_outcome(command_status, local_outcome)

    submit_action = _field(projection, "submit_action")
    cancel_action = _field(projection, "cancel_action")
    unknown_resolution = _field(projection, "unknown_resolution")
    provider_order_state = None
    provider_order_source_kind = None
    cancel_action_state = None
    cancel_action_source_kind = None
    target_order_state = None
    target_order_source_kind = None
    cancel_action_id = None
    cancel_target = None

    if expected.operation == "SUBMIT":
        if submit_action is None or cancel_action is not None:
            raise CtpDispatchReadModelError("CTP submit projection has the wrong action shape")
        if (
            _field(submit_action, "managed_intent_id") != expected.managed_intent_id
            or _field(submit_action, "runtime_order_id") != expected.runtime_order_id
            or _field(submit_action, "order_ref") != expected.order_ref
        ):
            raise CtpDispatchReadModelError("CTP submit action identity does not match")
        provider_order_state, provider_order_source_kind = _order_state(
            _field(submit_action, "order_state")
        )
    else:
        if cancel_action is None or submit_action is not None:
            raise CtpDispatchReadModelError("CTP cancel projection has the wrong action shape")
        assert expected.cancel_binding is not None
        target = _field(cancel_action, "target_order")
        expected_target = expected.cancel_binding.target
        cancel_action_id = _field(cancel_action, "managed_action_id")
        if cancel_action_id != expected.cancel_binding.managed_action_id:
            raise CtpDispatchReadModelError("CTP cancel action identity does not match")
        if (
            _field(target, "managed_intent_id") != expected.managed_intent_id
            or _field(target, "runtime_order_id") != expected.runtime_order_id
            or _field(target, "order_ref") != expected.order_ref
            or _field(target, "exchange_id") != expected_target.exchange_id
            or _field(target, "order_sys_id") != expected_target.order_sys_id
            or type(_field(target, "front_id")) is not int
            or _field(target, "front_id") != expected_target.front_id
            or type(_field(target, "session_id")) is not int
            or _field(target, "session_id") != expected_target.session_id
        ):
            raise CtpDispatchReadModelError("CTP cancel target identity does not match")
        cancel_target = expected_target
        cancel_action_state, cancel_action_source_kind = _cancel_action_state(cancel_action)
        target_order_state, target_order_source_kind = _order_state(_field(target, "order_state"))

    resolution_order_state = None
    resolution_cancel_state = None
    if unknown_resolution is not None:
        if command_status != "UNKNOWN":
            raise CtpDispatchReadModelError("CTP resolution is attached to a non-UNKNOWN command")
        resolution_order_state = _field(unknown_resolution, "order_terminal_state")
        resolution_cancel_state = _field(unknown_resolution, "cancel_action_terminal_state")
        verified_at_ns = _field(unknown_resolution, "verified_at_ns")
        resolved_at_ns = _field(unknown_resolution, "resolved_at_ns")
        if (
            type(resolution_order_state) is not str
            or resolution_order_state not in _ORDER_TERMINAL_STATES
            or type(verified_at_ns) is not int
            or type(resolved_at_ns) is not int
            or verified_at_ns <= 0
            or resolved_at_ns < verified_at_ns
        ):
            raise CtpDispatchReadModelError("invalid CTP UNKNOWN order resolution")
        if expected.operation == "SUBMIT":
            if (
                resolution_cancel_state is not None
                or provider_order_state != resolution_order_state
            ):
                raise CtpDispatchReadModelError("CTP submit resolution does not match order state")
        elif (
            type(resolution_cancel_state) is not str
            or resolution_cancel_state not in _CANCEL_ACTION_TERMINAL_STATES
            or cancel_action_state != resolution_cancel_state
            or target_order_state != resolution_order_state
        ):
            raise CtpDispatchReadModelError("CTP cancel resolution does not match projected states")

    if local_outcome == "REJECTED" and any(
        value is not None
        for value in (
            provider_order_state,
            cancel_action_state,
            target_order_state,
            unknown_resolution,
        )
    ):
        raise CtpDispatchReadModelError(
            "locally rejected CTP dispatch cannot carry provider projection state"
        )

    unresolved = command_status == "CLAIMED" or (
        command_status == "UNKNOWN" and unknown_resolution is None
    )
    return CtpManagedDispatchReadModel(
        command_id=command_id,
        operation=operation,
        command_status=command_status,
        local_dispatch_outcome=local_outcome,
        managed_intent_id=expected.managed_intent_id,
        runtime_order_id=expected.runtime_order_id,
        order_ref=expected.order_ref,
        cancel_action_id=cancel_action_id,
        cancel_target=cancel_target,
        provider_order_state=provider_order_state,
        provider_order_source_kind=provider_order_source_kind,
        cancel_action_state=cancel_action_state,
        cancel_action_source_kind=cancel_action_source_kind,
        target_order_state=target_order_state,
        target_order_source_kind=target_order_source_kind,
        unknown_resolution_order_state=resolution_order_state,
        unknown_resolution_cancel_action_state=resolution_cancel_state,
        action_requires_write_freeze=unresolved,
    )


def _validate_local_outcome(command_status: str, value: Any) -> None:
    if value is not None and (
        type(value) is not str or value not in {"QUEUED", "REJECTED", "UNKNOWN"}
    ):
        raise CtpDispatchReadModelError("invalid local CTP dispatch outcome")
    expected = {
        "READY": {None},
        "CLAIMED": {None},
        "COMPLETED": {"QUEUED", "REJECTED"},
        "UNKNOWN": {"UNKNOWN"},
    }
    if value not in expected[command_status]:
        raise CtpDispatchReadModelError("CTP local outcome conflicts with command status")


def _order_state(value: Any) -> tuple[Optional[str], Optional[str]]:
    provider_state = _field(value, "provider_state")
    terminal = _field(value, "terminal")
    source_kind = _field(value, "source_kind")
    updated_at_ns = _field(value, "updated_at_ns")
    if provider_state is None:
        if any(item is not None for item in (terminal, source_kind, updated_at_ns)):
            raise CtpDispatchReadModelError("absent CTP order state contains partial evidence")
        return None, None
    if type(provider_state) is not str or provider_state not in _ORDER_STATES:
        raise CtpDispatchReadModelError("invalid durable CTP order state")
    expected_terminal = provider_state in _ORDER_TERMINAL_STATES
    if (
        type(terminal) is not bool
        or terminal is not expected_terminal
        or type(source_kind) is not str
        or source_kind not in {"CALLBACK", "RECONCILIATION"}
        or type(updated_at_ns) is not int
        or updated_at_ns <= 0
    ):
        raise CtpDispatchReadModelError("invalid durable CTP order state")
    return provider_state, source_kind


def _cancel_action_state(value: Any) -> tuple[Optional[str], Optional[str]]:
    action_state = _field(value, "action_state")
    terminal = _field(value, "terminal")
    source_kind = _field(value, "source_kind")
    updated_at_ns = _field(value, "updated_at_ns")
    if action_state is None:
        if any(item is not None for item in (terminal, source_kind, updated_at_ns)):
            raise CtpDispatchReadModelError(
                "absent CTP cancel-action state contains partial evidence"
            )
        return None, None
    if type(action_state) is not str or action_state not in _CANCEL_ACTION_STATES:
        raise CtpDispatchReadModelError("invalid durable CTP cancel-action state")
    expected_terminal = action_state in _CANCEL_ACTION_TERMINAL_STATES
    if (
        type(terminal) is not bool
        or terminal is not expected_terminal
        or type(source_kind) is not str
        or source_kind not in {"CALLBACK", "RECONCILIATION"}
        or type(updated_at_ns) is not int
        or updated_at_ns <= 0
    ):
        raise CtpDispatchReadModelError("invalid durable CTP cancel-action state")
    return action_state, source_kind


def _field(value: Any, name: str) -> Any:
    try:
        return getattr(value, name)
    except AttributeError as error:
        raise CtpDispatchReadModelError("CTP projection is missing " + name) from error


def _identity(value: Any, name: str) -> None:
    if type(value) is not str or not _IDENTITY_RE.fullmatch(value):
        raise CtpDispatchReadModelError("invalid CTP " + name)


__all__ = [
    "CtpDispatchProjectionReader",
    "CtpDispatchReadExpectation",
    "CtpDispatchReadModelError",
    "CtpManagedDispatchReadModel",
    "read_ctp_managed_dispatch_model",
    "reduce_ctp_managed_dispatch_projection",
]
