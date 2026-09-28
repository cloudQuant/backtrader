"""Exact, non-authorizing CTP cancel target binding for the managed handoff.

The version-1 handoff types OrderRef, OrderSysID, FrontID, and SessionID, but
does not type ExchangeID as part of its target.  This adapter closes that
structural gap before a future SDK bridge maps the cancellation into the SDK's
typed CTP outbox command.  It neither authenticates provider evidence nor
produces a provider observation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .ctp_managed_handoff import CtpManagedCancelHandoff, CtpManagedHandoffError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ORDER_REF_RE = re.compile(r"^[0-9]{12}$")
_EXCHANGE_ID_RE = re.compile(r"^[A-Z0-9]{1,8}$")
_ORDER_SYS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_BINDING_DOMAIN = b"backtrader.ctp.managed-cancel-binding.v1\0"


def _reject(reason: str) -> None:
    raise CtpManagedHandoffError(reason)


@dataclass(frozen=True)
class CtpManagedCancelTargetV1:
    """Complete native order target tuple required to correlate a cancel."""

    order_ref: str
    exchange_id: str
    order_sys_id: str
    front_id: int
    session_id: int

    def __post_init__(self) -> None:
        if type(self.order_ref) is not str or not _ORDER_REF_RE.fullmatch(self.order_ref):
            _reject("invalid_ctp_cancel_target_order_ref")
        if type(self.exchange_id) is not str or not _EXCHANGE_ID_RE.fullmatch(self.exchange_id):
            _reject("invalid_ctp_cancel_target_exchange_id")
        if type(self.order_sys_id) is not str or not _ORDER_SYS_ID_RE.fullmatch(
            self.order_sys_id
        ):
            _reject("invalid_ctp_cancel_target_order_sys_id")
        if type(self.front_id) is not int or self.front_id <= 0:
            _reject("invalid_ctp_cancel_target_front_id")
        if type(self.session_id) is not int or self.session_id <= 0:
            _reject("invalid_ctp_cancel_target_session_id")


@dataclass(frozen=True)
class CtpManagedCancelActionBindingV1:
    """Structural binding of one managed cancel action to its exact target.

    ``managed_action_id`` identifies this cancel action. ``target`` identifies
    the order the action addresses.  The digest binds those values to the
    Backtrader handoff request digest; it carries no dispatch or ACK authority.
    """

    handoff_request_digest: str
    managed_action_id: str
    target: CtpManagedCancelTargetV1
    version: int = 1
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _reject("unsupported_ctp_cancel_binding_version")
        if type(self.handoff_request_digest) is not str or not _SHA256_RE.fullmatch(
            self.handoff_request_digest
        ):
            _reject("invalid_ctp_cancel_binding_handoff_digest")
        if (
            type(self.managed_action_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.managed_action_id)
        ):
            _reject("invalid_ctp_cancel_binding_action_id")
        if type(self.target) is not CtpManagedCancelTargetV1:
            _reject("typed_ctp_cancel_target_required")
        payload = {
            "version": self.version,
            "handoff_request_digest": self.handoff_request_digest,
            "managed_action_id": self.managed_action_id,
            "target": {
                "order_ref": self.target.order_ref,
                "exchange_id": self.target.exchange_id,
                "order_sys_id": self.target.order_sys_id,
                "front_id": self.target.front_id,
                "session_id": self.target.session_id,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        digest = hashlib.sha256(_BINDING_DOMAIN + encoded).hexdigest()
        object.__setattr__(self, "binding_digest", digest)


def bind_ctp_managed_cancel_handoff(
    handoff: Any,
    *,
    target: CtpManagedCancelTargetV1,
) -> CtpManagedCancelActionBindingV1:
    """Require the handoff request to echo a separately typed full target.

    ``target`` should come from the caller's already-established native order
    identity.  This function compares fields only; it does not establish how
    that identity was observed or authenticate the source.
    """

    if type(handoff) is not CtpManagedCancelHandoff:
        _reject("typed_ctp_managed_cancel_handoff_required")
    if type(target) is not CtpManagedCancelTargetV1:
        _reject("typed_ctp_cancel_target_required")
    if (
        handoff.target_order_ref != target.order_ref
        or handoff.target_order_sys_id != target.order_sys_id
        or handoff.target_front_id != target.front_id
        or handoff.target_session_id != target.session_id
    ):
        _reject("ctp_cancel_handoff_target_mismatch")

    fields = dict(handoff.request_fields)
    expected = {
        "OrderRef": (target.order_ref, str),
        "ExchangeID": (target.exchange_id, str),
        "OrderSysID": (target.order_sys_id, str),
        "FrontID": (target.front_id, int),
        "SessionID": (target.session_id, int),
    }
    for field_name, (expected_value, expected_type) in expected.items():
        actual = fields.get(field_name)
        if type(actual) is not expected_type or actual != expected_value:
            _reject("ctp_cancel_handoff_" + field_name.lower() + "_mismatch")

    return CtpManagedCancelActionBindingV1(
        handoff_request_digest=handoff.request_digest,
        managed_action_id=handoff.managed_cancel_intent_id,
        target=target,
    )


__all__ = [
    "CtpManagedCancelActionBindingV1",
    "CtpManagedCancelTargetV1",
    "bind_ctp_managed_cancel_handoff",
]
