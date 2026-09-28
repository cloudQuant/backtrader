"""Pure, versioned Backtrader-side contracts for managed CTP handoff.

These immutable values bind one managed intent or cancel action to its exact
execution scope, account key, trading day, and native CTP identifiers. They
carry no authorization and perform no provider, SDK, or secret access. A local
Store queue receipt and a native API submission receipt are distinct types;
neither is evidence of a provider acknowledgement. ``request_fields`` contains
the exact supplied immutable scalar inputs included in the digest; it does not
certify that all native CTP-required fields are present.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Tuple


CTP_MANAGED_HANDOFF_VERSION = 1
_SCOPE_KEY_RE = re.compile(r"^scope:[0-9a-f]{64}$")
_ACCOUNT_KEY_RE = re.compile(r"^account:[0-9a-f]{64}$")
_RUNTIME_ORDER_ID_RE = re.compile(r"^bt-managed-v1:[0-9a-f]{64}$")
_ORDER_REF_RE = re.compile(r"^[0-9]{12}$")
_MANAGED_INTENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_NATIVE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_QUEUE_RECEIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_HANDOFF_DOMAIN = b"backtrader.ctp.managed-handoff.v1\0"


class CtpManagedHandoffError(ValueError):
    """A CTP managed handoff contract is malformed or mismatched."""


def _reject(reason: str) -> None:
    raise CtpManagedHandoffError(reason)


def _validate_version(value: Any) -> None:
    if type(value) is not int or value != CTP_MANAGED_HANDOFF_VERSION:
        _reject("unsupported_ctp_managed_handoff_version")


def _validate_scope_key(value: Any) -> str:
    if type(value) is not str or not _SCOPE_KEY_RE.fullmatch(value):
        _reject("invalid_execution_scope_key")
    return value


def _validate_account_key(value: Any) -> str:
    if type(value) is not str or not _ACCOUNT_KEY_RE.fullmatch(value):
        _reject("invalid_execution_account_key")
    return value


def _validate_trading_day(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
        _reject("invalid_trading_day")
    try:
        parsed = _datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        _reject("invalid_trading_day")
    if parsed.strftime("%Y%m%d") != value:
        _reject("invalid_trading_day")
    return value


def _validate_managed_intent_id(value: Any) -> str:
    if type(value) is not str or not _MANAGED_INTENT_ID_RE.fullmatch(value):
        _reject("invalid_managed_intent_id")
    return value


def _validate_action_id(value: Any, name: str) -> str:
    if type(value) is not str or not _ACTION_ID_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _validate_runtime_order_id(value: Any) -> str:
    if type(value) is not str or not _RUNTIME_ORDER_ID_RE.fullmatch(value):
        _reject("invalid_runtime_order_id")
    return value


def _validate_order_ref(value: Any, name: str = "ctp_order_ref") -> str:
    if type(value) is not str or not _ORDER_REF_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _validate_native_id(value: Any, name: str) -> str:
    if type(value) is not str or not _NATIVE_ID_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _typed_scalar(value: Any) -> list[Any]:
    """Return a stable JSON-safe encoding that preserves the scalar's type."""

    if value is None:
        return ["none", None]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", value]
    if type(value) is str:
        if not value.isascii() or "\x00" in value:
            _reject("invalid_ctp_request_text")
        return ["str", value]
    if type(value) is Decimal:
        if not value.is_finite():
            _reject("invalid_ctp_request_decimal")
        return ["decimal", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            _reject("invalid_ctp_request_float")
        return ["float64", value.hex()]
    _reject("unsupported_ctp_request_value")


def freeze_ctp_request_fields(fields: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    """Freeze a native request mapping into the contract's canonical tuple.

    Only a plain ``dict`` is accepted so a custom Mapping cannot execute
    caller-controlled behavior during contract construction. Values must be
    immutable CTP scalar types; lists, nested objects, and SDK objects reject.
    The tuple is the input to the request digest, not proof of native field
    completeness.
    """

    if type(fields) is not dict or not fields:
        _reject("ctp_request_fields_must_be_a_nonempty_dict")
    if any(type(name) is not str for name in fields):
        _reject("invalid_ctp_request_field_name")
    result = []
    for name in sorted(fields):
        if type(name) is not str or not _FIELD_NAME_RE.fullmatch(name):
            _reject("invalid_ctp_request_field_name")
        value = fields[name]
        _typed_scalar(value)
        result.append((name, value))
    return tuple(result)


def _validate_request_fields(value: Any) -> Tuple[Tuple[str, Any], ...]:
    if type(value) is not tuple or not value:
        _reject("ctp_request_fields_must_be_a_canonical_tuple")
    frozen = []
    seen = set()
    previous = None
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            _reject("ctp_request_fields_must_be_a_canonical_tuple")
        name, field_value = pair
        if type(name) is not str or not _FIELD_NAME_RE.fullmatch(name):
            _reject("invalid_ctp_request_field_name")
        if name in seen or (previous is not None and name <= previous):
            _reject("ctp_request_fields_not_canonical")
        _typed_scalar(field_value)
        seen.add(name)
        previous = name
        frozen.append((name, field_value))
    return tuple(frozen)


def _request_field_map(fields: Tuple[Tuple[str, Any], ...]) -> dict[str, Any]:
    return dict(fields)


def _validate_embedded_identity(
    fields: Tuple[Tuple[str, Any], ...],
    *,
    runtime_order_id: str,
    managed_intent_id: str,
    runtime_action_id: str | None = None,
) -> None:
    field_map = _request_field_map(fields)
    for name, expected in (
        ("runtime_order_id", runtime_order_id),
        ("managed_intent_id", managed_intent_id),
    ):
        if name in field_map and field_map[name] != expected:
            _reject("ctp_request_" + name + "_mismatch")
    if runtime_action_id is not None:
        for name in ("runtime_action_id", "managed_cancel_intent_id"):
            if name in field_map and field_map[name] != runtime_action_id:
                _reject("ctp_request_" + name + "_mismatch")


def _digest_request(document: dict[str, Any]) -> str:
    serialized = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(_HANDOFF_DOMAIN + serialized).hexdigest()


def _encoded_fields(fields: Tuple[Tuple[str, Any], ...]) -> list[list[Any]]:
    return [[name, _typed_scalar(value)] for name, value in fields]


@dataclass(frozen=True)
class CtpManagedSubmitHandoff:
    """Exact, non-authorizing submit projection for one managed CTP intent."""

    scope_key: str
    account_key: str
    trading_day: str
    managed_intent_id: str
    runtime_order_id: str
    ctp_order_ref: str
    request_fields: Tuple[Tuple[str, Any], ...]
    version: int = CTP_MANAGED_HANDOFF_VERSION
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_version(self.version)
        _validate_scope_key(self.scope_key)
        _validate_account_key(self.account_key)
        _validate_trading_day(self.trading_day)
        _validate_managed_intent_id(self.managed_intent_id)
        _validate_runtime_order_id(self.runtime_order_id)
        _validate_order_ref(self.ctp_order_ref)
        fields = _validate_request_fields(self.request_fields)
        object.__setattr__(self, "request_fields", fields)
        native = _request_field_map(fields)
        if native.get("OrderRef") != self.ctp_order_ref or type(native.get("OrderRef")) is not str:
            _reject("ctp_submit_order_ref_mismatch")
        _validate_embedded_identity(
            fields,
            runtime_order_id=self.runtime_order_id,
            managed_intent_id=self.managed_intent_id,
        )
        digest = _digest_request(
            {
                "version": self.version,
                "operation": "SUBMIT",
                "scope_key": self.scope_key,
                "account_key": self.account_key,
                "trading_day": self.trading_day,
                "managed_intent_id": self.managed_intent_id,
                "runtime_order_id": self.runtime_order_id,
                "ctp_order_ref": self.ctp_order_ref,
                "request_fields": _encoded_fields(fields),
            }
        )
        object.__setattr__(self, "request_digest", digest)

    @property
    def operation(self) -> str:
        return "SUBMIT"


@dataclass(frozen=True)
class CtpManagedCancelHandoff:
    """Exact, non-authorizing cancel action and native target projection."""

    scope_key: str
    account_key: str
    trading_day: str
    managed_intent_id: str
    runtime_order_id: str
    ctp_order_ref: str
    runtime_action_id: str
    managed_cancel_intent_id: str
    target_order_ref: str
    target_order_sys_id: str
    target_front_id: int
    target_session_id: int
    request_fields: Tuple[Tuple[str, Any], ...]
    version: int = CTP_MANAGED_HANDOFF_VERSION
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_version(self.version)
        _validate_scope_key(self.scope_key)
        _validate_account_key(self.account_key)
        _validate_trading_day(self.trading_day)
        _validate_managed_intent_id(self.managed_intent_id)
        _validate_runtime_order_id(self.runtime_order_id)
        _validate_order_ref(self.ctp_order_ref)
        _validate_action_id(self.runtime_action_id, "runtime_action_id")
        _validate_action_id(self.managed_cancel_intent_id, "managed_cancel_intent_id")
        if self.runtime_action_id != self.managed_cancel_intent_id:
            _reject("runtime_action_id_must_equal_managed_cancel_intent_id")
        _validate_order_ref(self.target_order_ref, "target_order_ref")
        _validate_native_id(self.target_order_sys_id, "target_order_sys_id")
        if type(self.target_front_id) is not int or self.target_front_id <= 0:
            _reject("invalid_target_front_id")
        if type(self.target_session_id) is not int or self.target_session_id <= 0:
            _reject("invalid_target_session_id")
        if self.target_order_ref != self.ctp_order_ref:
            _reject("cancel_target_order_ref_mismatch")
        fields = _validate_request_fields(self.request_fields)
        object.__setattr__(self, "request_fields", fields)
        native = _request_field_map(fields)
        expected_target = {
            "OrderRef": (self.target_order_ref, str),
            "OrderSysID": (self.target_order_sys_id, str),
            "FrontID": (self.target_front_id, int),
            "SessionID": (self.target_session_id, int),
        }
        for name, (expected, expected_type) in expected_target.items():
            if type(native.get(name)) is not expected_type or native[name] != expected:
                _reject("ctp_cancel_" + name.lower() + "_mismatch")
        _validate_embedded_identity(
            fields,
            runtime_order_id=self.runtime_order_id,
            managed_intent_id=self.managed_intent_id,
            runtime_action_id=self.runtime_action_id,
        )
        digest = _digest_request(
            {
                "version": self.version,
                "operation": "CANCEL",
                "scope_key": self.scope_key,
                "account_key": self.account_key,
                "trading_day": self.trading_day,
                "managed_intent_id": self.managed_intent_id,
                "runtime_order_id": self.runtime_order_id,
                "ctp_order_ref": self.ctp_order_ref,
                "runtime_action_id": self.runtime_action_id,
                "managed_cancel_intent_id": self.managed_cancel_intent_id,
                "target": [
                    self.target_order_ref,
                    self.target_order_sys_id,
                    self.target_front_id,
                    self.target_session_id,
                ],
                "request_fields": _encoded_fields(fields),
            }
        )
        object.__setattr__(self, "request_digest", digest)

    @property
    def operation(self) -> str:
        return "CANCEL"


def _require_handoff(value: Any) -> CtpManagedSubmitHandoff | CtpManagedCancelHandoff:
    if type(value) not in (CtpManagedSubmitHandoff, CtpManagedCancelHandoff):
        _reject("typed_ctp_managed_handoff_required")
    return value


@dataclass(frozen=True)
class CtpManagedLocalQueuedReceipt:
    """Store-local queue receipt; it is not a native submission or provider ACK."""

    operation: str
    request_digest: str
    queue_receipt_id: str
    queue_depth: int
    version: int = CTP_MANAGED_HANDOFF_VERSION

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if type(self.operation) is not str or self.operation not in ("SUBMIT", "CANCEL"):
            _reject("invalid_local_queue_operation")
        if type(self.request_digest) is not str or not _SHA256_RE.fullmatch(self.request_digest):
            _reject("invalid_local_queue_request_digest")
        if type(self.queue_receipt_id) is not str or not _QUEUE_RECEIPT_ID_RE.fullmatch(
            self.queue_receipt_id
        ):
            _reject("invalid_local_queue_receipt_id")
        if type(self.queue_depth) is not int or self.queue_depth < 0:
            _reject("invalid_local_queue_depth")

    @property
    def state(self) -> str:
        return "LOCAL_QUEUED"

    @property
    def provider_acknowledged(self) -> bool:
        return False


@dataclass(frozen=True)
class CtpManagedNativeSubmissionReceipt:
    """Successful native API submission-call receipt, before provider ACK."""

    operation: str
    request_digest: str
    echoed_handoff: CtpManagedSubmitHandoff | CtpManagedCancelHandoff
    native_request_id: int
    submit_code: int
    version: int = CTP_MANAGED_HANDOFF_VERSION

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if type(self.operation) is not str or self.operation not in ("SUBMIT", "CANCEL"):
            _reject("invalid_native_submission_operation")
        if type(self.request_digest) is not str or not _SHA256_RE.fullmatch(self.request_digest):
            _reject("invalid_native_submission_request_digest")
        echoed_handoff = _require_handoff(self.echoed_handoff)
        if (
            self.operation != echoed_handoff.operation
            or self.request_digest != echoed_handoff.request_digest
        ):
            _reject("native_submission_receipt_handoff_mismatch")
        if type(self.native_request_id) is not int or self.native_request_id <= 0:
            _reject("invalid_native_request_id")
        if type(self.submit_code) is not int or self.submit_code != 0:
            _reject("native_submission_not_accepted")

    @property
    def state(self) -> str:
        return "NATIVE_SUBMITTED"

    @property
    def provider_acknowledged(self) -> bool:
        return False


def require_local_queued_receipt(receipt: Any, handoff: Any) -> CtpManagedLocalQueuedReceipt:
    """Require a local queue receipt correlated to one exact handoff digest."""

    typed_handoff = _require_handoff(handoff)
    if (
        type(receipt) is not CtpManagedLocalQueuedReceipt
        or receipt.operation != typed_handoff.operation
        or receipt.request_digest != typed_handoff.request_digest
    ):
        _reject("local_queue_receipt_handoff_mismatch")
    return receipt


def require_native_submission_receipt(
    receipt: Any, handoff: Any
) -> CtpManagedNativeSubmissionReceipt:
    """Require a native submit-call receipt; a Store queue receipt cannot pass."""

    typed_handoff = _require_handoff(handoff)
    if (
        type(receipt) is not CtpManagedNativeSubmissionReceipt
        or receipt.operation != typed_handoff.operation
        or receipt.request_digest != typed_handoff.request_digest
        or type(receipt.echoed_handoff) is not type(typed_handoff)
        or receipt.echoed_handoff != typed_handoff
    ):
        _reject("native_submission_receipt_handoff_mismatch")
    return receipt


__all__ = [
    "CTP_MANAGED_HANDOFF_VERSION",
    "CtpManagedCancelHandoff",
    "CtpManagedHandoffError",
    "CtpManagedLocalQueuedReceipt",
    "CtpManagedNativeSubmissionReceipt",
    "CtpManagedSubmitHandoff",
    "freeze_ctp_request_fields",
    "require_local_queued_receipt",
    "require_native_submission_receipt",
]
