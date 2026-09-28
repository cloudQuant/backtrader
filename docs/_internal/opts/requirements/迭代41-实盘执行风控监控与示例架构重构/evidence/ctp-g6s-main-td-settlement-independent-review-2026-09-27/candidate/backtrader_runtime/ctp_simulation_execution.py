"""Narrow, receipt-bound CTP SimNow execution boundary.

This module is deliberately not registered by the default runtime inventory.
Callers must supply a sealed sandbox runtime, a code-owned registration, an
approval verifier, an account-wide writer fence, a native query evidence
verifier and a native session factory. The factory is called only after static
admission and acquisition of the local cross-process account flow lease.
Production environments are rejected.

The native factory adapter is responsible for mapping the typed requests to
the SDK's gated ``submit_order_insert`` / ``submit_order_action`` methods.
``CtpSimulationQueryResult.complete`` is only a local data contract: a true
value is not native provenance, complete pagination, or a terminal callback
certificate. The injected evidence verifier must bind native request history,
account, TradingDay, connection generation and full query coverage, then
recheck late callbacks after the last query. An opt-in ``TraderClient`` port
is available in ``ctp_trader_client_port.py``, but the default inventory/CLI
does not construct it and no trusted evidence verifier is provided. A request
return code is never treated as an exchange acknowledgement. Ambiguous
dispatches are journaled as UNKNOWN and can only be cleared by verified order,
trade and position queries. After restart, absent volatile cancel callback
history may resolve a pending intent only when those verified queries prove the
exact target is CANCELED and its trade/position deltas match. The journal then
records ``TARGET_TERMINAL``; it does not claim the cancel request was accepted.

The local lease protects cooperating processes on the same host, OS user and
state root. It does not fence another OS user, host or SDK process. Before a
native adapter can be used, its injected account-wide writer fence must provide
the single-writer authority for the whole account; the SDK currently derives
the TD flow directory from broker/user and can share it between processes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, List, NoReturn, Optional, Protocol, Tuple, cast
from urllib.parse import urlsplit

from .config import CtpPrivateConfig
from .errors import RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_ORDER_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_SIMNOW_ENVIRONMENT = "simnow"
_SIMNOW_SDK_PROFILE = "config_front_pair"
_MANAGED_CAPABILITIES = ("execution", "risk", "monitor")
_SIDES = frozenset(("BUY", "SELL"))
_ORDER_STATES = frozenset(
    ("DISPATCHING", "UNKNOWN", "PENDING", "OPEN", "PARTIAL", "CANCEL_PENDING")
)
_PENDING_CANCEL_STATES = frozenset(("DISPATCHING", "UNKNOWN", "CANCEL_PENDING"))
_TERMINAL_STATUSES = frozenset(("FILLED", "CANCELED", "REJECTED"))
_JOURNAL_SCOPE_SCHEMA_VERSION = 2
_MAX_JOURNAL_SCOPE_HISTORY = 64
_FRONT_PAIR_SET_DOMAIN = b"backtrader-ctp-simnow-front-pair-set-v1\0"
_TERMINAL_JOURNAL_STATES = frozenset(
    ("FILLED", "CANCELED", "REJECTED", "TARGET_TERMINAL")
)
_POISONED_LEASES: List["CtpAccountFlowLease"] = []
_POISONED_LEASES_LOCK = threading.Lock()


class CtpSimulationExecutionError(ValueError):
    """A redacted, fail-closed simulation execution rejection."""

    def __init__(self, reason: str, message: Optional[str] = None) -> None:
        self.reason = reason
        super().__init__(message or reason.replace("_", " "))


def _reject(reason: str, message: Optional[str] = None) -> NoReturn:
    raise CtpSimulationExecutionError(reason, message)


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) not in (str, int, float, Decimal):
        _reject("invalid_" + name)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _reject("invalid_" + name)
    if not result.is_finite():
        _reject("invalid_" + name)
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _front_pair_set_digest(front_pairs: Tuple[Tuple[str, str], ...]) -> str:
    """Hash the ordered MD/TD candidate set using the selector contract."""

    serialized = json.dumps(
        [[md_front, td_front] for md_front, td_front in front_pairs],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(_FRONT_PAIR_SET_DOMAIN + serialized).hexdigest()


def _validate_front(value: Any, name: str) -> str:
    """Require one canonical TCP address without exposing malformed input."""

    if type(value) is not str or not value or value != value.strip():
        _reject("invalid_" + name)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        parsed = None
        port = None
    if (
        parsed is None
        or parsed.scheme != "tcp"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or ord(character) < 0x20 for character in value)
        or value != "tcp://{0}:{1}".format(parsed.hostname, port)
    ):
        _reject("invalid_" + name)
    return value


def _default_state_root() -> Path:
    """One OS-user-owned state root shared by all CTP execution runtimes."""

    return Path.home() / ".backtrader" / "ctp_simnow_execution"


def _prepare_state_root() -> Path:
    root = _default_state_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        _reject("execution_state_root_symlink")
    if os.name != "nt":
        os.chmod(str(root), 0o700)
    return root


def _retain_poisoned_lease(lease: "CtpAccountFlowLease") -> None:
    """Keep a failed-close owner's OS lock until supervised process exit."""

    if lease._fd is None:
        return
    with _POISONED_LEASES_LOCK:
        if not any(current is lease for current in _POISONED_LEASES):
            _POISONED_LEASES.append(lease)


@dataclass(frozen=True)
class CtpSimulationExecutionRegistration:
    """One exact code-owned sandbox route and bounded order envelope."""

    runtime_registration: RegisteredRuntime
    environment: str
    sdk_profile: str
    td_front: str
    md_front: str
    account_fingerprint_sha256: str
    allowed_secrets_ref: str
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    allowed_sides: Tuple[str, ...]
    quantity_step: int
    max_quantity: int
    max_gross_position: int
    min_price: Decimal
    max_price: Decimal
    price_tick: Decimal
    approval_key_id: str
    approval_ttl_seconds: float = 30.0
    front_pair_set_sha256: Optional[str] = None
    config_digest: Optional[str] = None
    effective_digest: Optional[str] = None
    # Profile-backed execution binds the exact selected profile and its
    # receipt into this identity; neither value is read from inert legacy
    # registration fields.
    profile_digest: Optional[str] = None
    profile_approval_receipt_digest: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.runtime_registration) is not RegisteredRuntime:
            _reject("registration_required")
        if self.environment != _SIMNOW_ENVIRONMENT or self.sdk_profile != _SIMNOW_SDK_PROFILE:
            _reject("environment_profile_mismatch")
        object.__setattr__(self, "td_front", _validate_front(self.td_front, "td_front"))
        object.__setattr__(self, "md_front", _validate_front(self.md_front, "md_front"))
        _digest(self.account_fingerprint_sha256, "account_fingerprint_sha256")
        if (
            type(self.allowed_secrets_ref) is not str
            or not self.allowed_secrets_ref
            or self.allowed_secrets_ref != self.allowed_secrets_ref.strip()
            or any(char.isspace() for char in self.allowed_secrets_ref)
        ):
            _reject("invalid_secrets_reference")
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            _reject("invalid_instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            _reject("invalid_exchange")
        if type(self.hedge_flag) is not str or self.hedge_flag not in ("1", "2", "3"):
            _reject("invalid_hedge_flag")
        sides = tuple(self.allowed_sides)
        if not sides or len(set(sides)) != len(sides) or any(side not in _SIDES for side in sides):
            _reject("invalid_allowed_sides")
        object.__setattr__(self, "allowed_sides", sides)
        if (
            type(self.quantity_step) is not int
            or self.quantity_step <= 0
            or type(self.max_quantity) is not int
            or self.max_quantity <= 0
            or self.max_quantity % self.quantity_step
            or type(self.max_gross_position) is not int
            or self.max_gross_position < self.max_quantity
        ):
            _reject("invalid_quantity_limits")
        minimum = _decimal(self.min_price, "minimum_price")
        maximum = _decimal(self.max_price, "maximum_price")
        tick = _decimal(self.price_tick, "price_tick")
        if minimum <= 0 or maximum < minimum or tick <= 0:
            _reject("invalid_price_limits")
        if (minimum / tick) != (minimum / tick).to_integral_value() or (maximum / tick) != (
            maximum / tick
        ).to_integral_value():
            _reject("price_limits_not_tick_aligned")
        object.__setattr__(self, "min_price", minimum)
        object.__setattr__(self, "max_price", maximum)
        object.__setattr__(self, "price_tick", tick)
        if type(self.approval_key_id) is not str or not _ID_RE.fullmatch(self.approval_key_id):
            _reject("invalid_approval_key_id")
        if self.front_pair_set_sha256 is not None:
            _digest(self.front_pair_set_sha256, "front_pair_set_sha256")
        if self.config_digest is not None:
            _digest(self.config_digest, "config_digest")
        if self.effective_digest is not None:
            _digest(self.effective_digest, "effective_digest")
        if self.profile_digest is not None:
            _digest(self.profile_digest, "profile_digest")
        if self.profile_approval_receipt_digest is not None:
            _digest(self.profile_approval_receipt_digest, "profile_approval_receipt_digest")
        if (self.profile_digest is None) != (self.profile_approval_receipt_digest is None):
            _reject("profile_approval_binding_incomplete")
        if (
            type(self.approval_ttl_seconds) not in (int, float)
            or not math.isfinite(float(self.approval_ttl_seconds))
            or not 0 < float(self.approval_ttl_seconds) <= 60.0
        ):
            _reject("invalid_approval_ttl")
        object.__setattr__(self, "approval_ttl_seconds", float(self.approval_ttl_seconds))

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical(
                {
                    "account_fingerprint_sha256": self.account_fingerprint_sha256,
                    "allowed_secrets_ref": self.allowed_secrets_ref,
                    "allowed_sides": self.allowed_sides,
                    "approval_key_id": self.approval_key_id,
                    "approval_receipt_digest": (
                        self.profile_approval_receipt_digest
                        if self.profile_digest is not None
                        else self.runtime_registration.approval_receipt_digest
                    ),
                    "config_digest": self.config_digest,
                    "environment": self.environment,
                    "effective_digest": self.effective_digest,
                    "exchange_id": self.exchange_id,
                    "hedge_flag": self.hedge_flag,
                    "instrument_id": self.instrument_id,
                    "max_price": str(self.max_price),
                    "max_quantity": self.max_quantity,
                    "max_gross_position": self.max_gross_position,
                    "min_price": str(self.min_price),
                    "price_tick": str(self.price_tick),
                    "profile_digest": self.profile_digest,
                    "front_pair_set_sha256": self.front_pair_set_sha256,
                    "quantity_step": self.quantity_step,
                    "runtime_id": self.runtime_registration.runtime_id,
                    "sdk_profile": self.sdk_profile,
                    "td_front": self.td_front,
                    "md_front": self.md_front,
                }
            )
        ).hexdigest()


def require_ctp_simulation_execution_admission(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: CtpSimulationExecutionRegistration,
) -> CtpSimulationExecutionRegistration:
    """Validate a sandbox receipt-required route before factory/credential I/O."""

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        registered = registry.require_runtime_dir(effective.config.strategy_dir)
    except (RuntimeConfigError, Exception):
        _reject("sealed_runtime_rejected")
    if type(registration) is not CtpSimulationExecutionRegistration:
        _reject("code_owned_registration_required")
    profile = effective.profile
    if registration.effective_digest is not None and registration.effective_digest != effective.effective_digest:
        _reject("registration_effective_digest_mismatch")
    if (
        registered is not effective.registration
        or registered is not registration.runtime_registration
    ):
        _reject("runtime_registration_mismatch")
    if profile is None:
        if (
            registration.profile_digest is not None
            or registration.profile_approval_receipt_digest is not None
            or registered.profiles
            or registered.allowed_presets != ("sandbox",)
            or registered.allowed_parameter_keys != ()
            or registered.allowed_secrets_refs != (registration.allowed_secrets_ref,)
            or registered.sandbox_write_policy != "receipt_required"
            or registered.approval_receipt_digest is None
            or registered.available_capabilities != _MANAGED_CAPABILITIES
            or registered.offline_managed_execution
        ):
            _reject("runtime_policy_mismatch")
    else:
        if (
            type(profile) is not RuntimeProfile
            or profile is not registered.profile_for("simulation", "sandbox")
            or profile.mode != "simulation"
            or profile.preset != "sandbox"
        ):
            _reject("effective_profile_mismatch")
        if (
            registered.allowed_presets != ()
            or registered.allowed_parameter_keys != ()
            or registered.allowed_secrets_refs != ("none",)
            or registered.available_capabilities != ()
            or registered.offline_managed_execution is not False
            or registered.sandbox_write_policy != "deny"
            or registered.approval_receipt_digest is not None
            or profile.allowed_parameter_keys != ()
            or profile.allowed_secrets_refs != (registration.allowed_secrets_ref,)
            or profile.available_capabilities != _MANAGED_CAPABILITIES
            or profile.offline_managed_execution is not False
            or profile.sandbox_write_policy != "receipt_required"
            or registration.allowed_secrets_ref != "config_yaml"
            or profile.approval_receipt_digest is None
        ):
            _reject("runtime_profile_policy_mismatch")
        if (
            registration.profile_digest != profile.digest
            or registration.profile_approval_receipt_digest != profile.approval_receipt_digest
        ):
            _reject("profile_scope_binding_mismatch")
        if (
            registration.effective_digest != effective.effective_digest
            or registration.config_digest != effective.config.config_digest
        ):
            _reject("profile_scope_digest_mismatch")
    if (
        effective.config.strategy_id != registered.strategy_id
        or effective.config.secrets_ref != registration.allowed_secrets_ref
        or tuple(effective.parameters) != ()
        or effective.mode != "simulation"
        or effective.preset != "sandbox"
        or effective.policy.environment != "sandbox"
        or effective.policy.mode != "simulation"
        or effective.required_capabilities != _MANAGED_CAPABILITIES
        or effective.allows_production_writes is not False
        or effective.allows_external_writes is not True
        or effective.order_route != "managed_execution"
        or effective.account_access != "sandbox_direct_provider"
        or effective.requires_approval is not True
        or effective.requires_live_confirmation is not False
    ):
        _reject("effective_policy_mismatch")

    # The account selector intentionally stays out of config_digest. Refresh
    # the protected source before native factory I/O so both an originally
    # private config and a stale effective config observe the current CTP block.
    try:
        current = validate_runtime_config(registered.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
    except Exception:
        _reject("sealed_ctp_runtime_config_rejected")
    if (
        current.registration is not registered
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
    ):
        _reject("sealed_ctp_runtime_config_changed")
    if profile is None:
        private = current.config.ctp_simnow or current.config.ctp
        if private is not None:
            _validate_registration_private_ctp_scope(
                private,
                registration,
                config_digest=current.config.config_digest,
            )
    else:
        current_profile = current.profile
        private = getattr(current.config, "ctp", None)
        legacy_private = getattr(current.config, "ctp_simnow", None)
        if (
            type(current_profile) is not RuntimeProfile
            or current_profile.digest != registration.profile_digest
            or current_profile.approval_receipt_digest
            != registration.profile_approval_receipt_digest
            or type(private) is not CtpPrivateConfig
            or (legacy_private is not None and legacy_private is not private)
        ):
            _reject("sealed_canonical_ctp_profile_scope_mismatch")
        _validate_registration_private_ctp_scope(
            private,
            registration,
            config_digest=current.config.config_digest,
        )
    return registration


def _validate_registration_private_ctp_scope(
    private: Any,
    registration: CtpSimulationExecutionRegistration,
    *,
    config_digest: str,
) -> None:
    """Bind execution identity and contract fields to a fresh sealed CTP block."""

    broker_id = getattr(private, "broker_id", None)
    user_id = getattr(private, "user_id", None)
    if type(broker_id) is not str or type(user_id) is not str:
        _reject("sealed_ctp_account_scope_invalid")
    expected_fingerprint = hashlib.sha256(
        "{0}:{1}".format(broker_id, user_id).encode("utf-8")
    ).hexdigest()[:16]
    expected_account_digest = hashlib.sha256(
        ("acct_" + expected_fingerprint).encode("ascii")
    ).hexdigest()
    if not hmac.compare_digest(
        registration.account_fingerprint_sha256, expected_account_digest
    ):
        _reject("sealed_ctp_account_scope_mismatch")

    if (
        getattr(private, "instrument_id", None) != registration.instrument_id
        or getattr(private, "exchange_id", None) != registration.exchange_id
        or getattr(private, "hedge_flag", None) != registration.hedge_flag
    ):
        _reject("sealed_ctp_contract_scope_mismatch")

    selected_pair = (registration.md_front, registration.td_front)
    raw_pairs = getattr(private, "front_pairs", None)
    if raw_pairs is None:
        md_front = getattr(private, "md_front", None)
        td_front = getattr(private, "td_front", None)
        raw_pairs = (({"md_front": md_front, "td_front": td_front}),)
    try:
        configured_pairs = tuple(
            (
                _validate_front(pair["md_front"], "md_front"),
                _validate_front(pair["td_front"], "td_front"),
            )
            for pair in raw_pairs
        )
    except (KeyError, TypeError):
        _reject("sealed_ctp_front_pair_set_invalid")
    if not configured_pairs or configured_pairs.count(selected_pair) != 1:
        _reject("sealed_ctp_front_pair_registration_mismatch")
    candidate_digest = _front_pair_set_digest(configured_pairs)
    if (
        registration.front_pair_set_sha256 is not None
        and registration.front_pair_set_sha256 != candidate_digest
    ):
        _reject("sealed_ctp_front_pair_set_mismatch")
    if (
        registration.config_digest is not None
        and registration.config_digest != config_digest
    ):
        _reject("sealed_ctp_config_scope_mismatch")


@dataclass(frozen=True)
class CtpSimulationWriteRequest:
    """One exact submit or cancel action covered by a short-lived approval."""

    action: str
    client_order_id: str
    instrument_id: str
    exchange_id: str
    side: str
    quantity: int
    limit_price: Decimal
    offset: str = "OPEN"
    hedge_flag: str = "1"
    target_order_sys_id: Optional[str] = None
    target_order_ref: Optional[str] = None
    target_front_id: Optional[int] = None
    target_session_id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.action not in ("SUBMIT", "CANCEL"):
            _reject("invalid_action")
        if type(self.client_order_id) is not str or not _ORDER_CLIENT_ID_RE.fullmatch(
            self.client_order_id
        ):
            _reject("invalid_client_order_id")
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            _reject("invalid_instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            _reject("invalid_exchange")
        if self.side not in _SIDES:
            _reject("invalid_side")
        if self.offset != "OPEN":
            _reject("execution_slice_only_supports_opening_orders")
        if self.hedge_flag not in ("1", "2", "3"):
            _reject("invalid_hedge_flag")
        if type(self.quantity) is not int or self.quantity <= 0:
            _reject("invalid_quantity")
        object.__setattr__(self, "limit_price", _decimal(self.limit_price, "limit_price"))
        if self.action == "CANCEL":
            if type(self.target_order_sys_id) is not str or not _ID_RE.fullmatch(
                self.target_order_sys_id
            ):
                _reject("cancel_target_required")
            if type(self.target_order_ref) is not str or not _ID_RE.fullmatch(
                self.target_order_ref
            ):
                _reject("cancel_order_ref_required")
            if type(self.target_front_id) is not int or self.target_front_id <= 0:
                _reject("cancel_front_id_required")
            if type(self.target_session_id) is not int or self.target_session_id <= 0:
                _reject("cancel_session_id_required")
        elif any(
            value is not None
            for value in (
                self.target_order_sys_id,
                self.target_order_ref,
                self.target_front_id,
                self.target_session_id,
            )
        ):
            _reject("submit_target_forbidden")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical(
                {
                    "action": self.action,
                    "client_order_id": self.client_order_id,
                    "exchange_id": self.exchange_id,
                    "instrument_id": self.instrument_id,
                    "limit_price": str(self.limit_price),
                    "offset": self.offset,
                    "hedge_flag": self.hedge_flag,
                    "quantity": self.quantity,
                    "side": self.side,
                    "target_order_sys_id": self.target_order_sys_id,
                    "target_order_ref": self.target_order_ref,
                    "target_front_id": self.target_front_id,
                    "target_session_id": self.target_session_id,
                }
            )
        ).hexdigest()


@dataclass(frozen=True)
class CtpSimulationWriteApproval:
    """Signed one-shot approval for one action payload."""

    approval_id: str
    key_id: str
    registration_digest: str
    receipt_digest: str
    account_fingerprint_sha256: str
    environment: str
    td_front: str
    md_front: str
    request_digest: str
    issued_at: float
    expires_at: float
    signature_hex: str

    def __post_init__(self) -> None:
        for name in (
            "approval_id",
            "key_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not _ID_RE.fullmatch(value):
                _reject("invalid_approval")
        for name in (
            "registration_digest",
            "receipt_digest",
            "account_fingerprint_sha256",
            "request_digest",
        ):
            _digest(getattr(self, name), name)
        if self.environment != _SIMNOW_ENVIRONMENT:
            _reject("approval_requires_simnow_environment")
        _validate_front(self.td_front, "td_front")
        _validate_front(self.md_front, "md_front")
        for value in (self.issued_at, self.expires_at):
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                _reject("invalid_approval_time")
        if self.expires_at <= self.issued_at:
            _reject("invalid_approval_window")
        if type(self.signature_hex) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.signature_hex
        ):
            _reject("invalid_approval_signature")

    def signed_payload(self) -> bytes:
        return _canonical(
            {
                "account_fingerprint_sha256": self.account_fingerprint_sha256,
                "approval_id": self.approval_id,
                "environment": self.environment,
                "td_front": self.td_front,
                "md_front": self.md_front,
                "expires_at": float(self.expires_at),
                "issued_at": float(self.issued_at),
                "key_id": self.key_id,
                "receipt_digest": self.receipt_digest,
                "registration_digest": self.registration_digest,
                "request_digest": self.request_digest,
            }
        )


class CtpSimulationApprovalVerifier(Protocol):
    """Verify approvals against an independently held operator key."""

    def verify(self, approval: CtpSimulationWriteApproval) -> bool: ...


class HmacCtpSimulationApprovalVerifier:
    """HMAC verifier; callers load its key from an OS secret store."""

    def __init__(self, key_id: str, key: bytes) -> None:
        if type(key_id) is not str or not _ID_RE.fullmatch(key_id):
            _reject("invalid_approval_key_id")
        if type(key) is not bytes or len(key) < 32:
            _reject("approval_key_unavailable")
        self._key_id = key_id
        self._key = bytes(key)

    def verify(self, approval: CtpSimulationWriteApproval) -> bool:
        if type(approval) is not CtpSimulationWriteApproval or approval.key_id != self._key_id:
            return False
        expected = hmac.new(self._key, approval.signed_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, approval.signature_hex)


@dataclass(frozen=True)
class CtpSimulationSessionIdentity:
    """Identity and gate state freshly reported by the native adapter."""

    environment: str
    sdk_profile: str
    td_front: str
    md_front: str
    account_fingerprint_sha256: str
    trading_day: str
    connection_generation: int
    production: bool
    native_gate_armed: bool
    native_simnow_managed_mode: bool = False

    def __post_init__(self) -> None:
        if self.environment != _SIMNOW_ENVIRONMENT or self.sdk_profile != _SIMNOW_SDK_PROFILE:
            _reject("session_profile_mismatch")
        _validate_front(self.td_front, "session_td_front")
        _validate_front(self.md_front, "session_md_front")
        _digest(self.account_fingerprint_sha256, "session_account_fingerprint")
        if type(self.trading_day) is not str or not re.fullmatch(r"[0-9]{8}", self.trading_day):
            _reject("invalid_trading_day")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            _reject("invalid_connection_generation")
        if self.production is not False:
            _reject("production_disabled")
        if type(self.native_gate_armed) is not bool:
            _reject("native_execution_gate_state_invalid")
        if type(self.native_simnow_managed_mode) is not bool:
            _reject("native_simnow_managed_mode_invalid")
        if self.native_gate_armed and self.native_simnow_managed_mode:
            _reject("native_execution_authorization_mode_invalid")


@dataclass(frozen=True)
class CtpSimulationDispatchReceipt:
    """Exact local CTP submission result bound to one managed intent.

    ``QUEUED`` means only that the native API accepted the request into its
    local dispatch path. It is not a provider acknowledgement. ``REJECTED``
    is reserved for a negative native submit code whose SDK evidence confirms
    the same request, account, session and target with no callback received.
    Any malformed or unproven result is ``UNKNOWN`` and must freeze writes
    until reconciliation.
    """

    operation: str
    outcome: str
    request_digest: str
    client_order_id: str
    managed_intent_id: str
    action_id: Optional[str]
    request_id: int
    submit_code: Optional[int]
    identity: CtpSimulationSessionIdentity
    local_rejection_verified: bool = False

    def __post_init__(self) -> None:
        if self.operation not in ("SUBMIT", "CANCEL"):
            _reject("native_dispatch_receipt_operation_invalid")
        if self.outcome not in ("QUEUED", "REJECTED", "UNKNOWN"):
            _reject("native_dispatch_receipt_outcome_invalid")
        _digest(self.request_digest, "native_dispatch_receipt_request_digest")
        if type(self.client_order_id) is not str or not _ORDER_CLIENT_ID_RE.fullmatch(
            self.client_order_id
        ):
            _reject("native_dispatch_receipt_order_identity_invalid")
        if (
            type(self.managed_intent_id) is not str
            or not self.managed_intent_id
            or self.managed_intent_id != self.managed_intent_id.strip()
            or len(self.managed_intent_id) > 256
            or not self.managed_intent_id.isascii()
            or any(
                not (character.isalnum() or character in "._:-")
                for character in self.managed_intent_id
            )
        ):
            _reject("native_dispatch_receipt_intent_identity_invalid")
        if self.operation == "SUBMIT":
            if self.action_id is not None:
                _reject("native_dispatch_receipt_action_id_invalid")
        elif type(self.action_id) is not str or not _ID_RE.fullmatch(self.action_id):
            _reject("native_dispatch_receipt_action_id_invalid")
        if type(self.request_id) is not int or self.request_id <= 0:
            _reject("native_dispatch_receipt_request_id_invalid")
        if self.submit_code is not None and type(self.submit_code) is not int:
            _reject("native_dispatch_receipt_submit_code_invalid")
        if type(self.local_rejection_verified) is not bool:
            _reject("native_dispatch_receipt_rejection_proof_invalid")
        if type(self.identity) is not CtpSimulationSessionIdentity:
            _reject("native_dispatch_receipt_session_identity_invalid")
        if self.outcome == "QUEUED" and (
            self.submit_code != 0 or self.local_rejection_verified
        ):
            _reject("native_dispatch_receipt_queue_result_invalid")
        if self.outcome == "REJECTED" and not (
            type(self.submit_code) is int
            and self.submit_code < 0
            and self.local_rejection_verified is True
        ):
            _reject("native_dispatch_receipt_rejection_unproven")
        if self.outcome == "UNKNOWN" and self.local_rejection_verified:
            _reject("native_dispatch_receipt_unknown_has_rejection_proof")

    @property
    def provider_acknowledged(self) -> bool:
        """A local submission receipt never proves a provider acknowledgement."""

        return False


class CtpSimulationAccountWriterFence(Protocol):
    """External, account-wide single-writer authority for a native session.

    This must fence every process/user/host that can access the SDK account and
    its CTP flow directory. The local file lease below cannot provide that
    guarantee by itself.
    """

    environment: str
    account_fingerprint_sha256: str
    fence_id: str

    def assert_active(self) -> None: ...


class CtpSimulationQueryEvidenceVerifier(Protocol):
    """Verify native request history, scope, coverage and callback quiescence.

    Returning true asserts the result came from the expected native query
    generation/account/TradingDay, all pages and terminal conditions are
    covered, and callbacks were rechecked after the final query. For
    ``account_open_orders`` it must prove the entire account's open-order set,
    not only the registered instrument. For ``cancel_requests`` it must prove
    terminal native request outcomes for every requested action ID. A restarted
    session may instead resolve a pending cancel intent from verified exact
    order, trade and position queries when the adapter explicitly reports its
    volatile cancel history absent; that outcome is persisted as
    ``TARGET_TERMINAL``, never as cancel-request acceptance. This module has no
    implementation that can make those assertions for TraderClient.
    """

    def verify(
        self,
        query_kind: str,
        result: "CtpSimulationQueryResult",
        *,
        expected_identity: CtpSimulationSessionIdentity,
        registration_digest: str,
    ) -> bool: ...


@dataclass(frozen=True)
class CtpSimulationOrderSnapshot:
    client_order_id: str
    instrument_id: str
    exchange_id: str
    side: str
    quantity: int
    limit_price: Decimal
    traded_quantity: int
    status: str
    order_ref: str
    order_sys_id: str
    front_id: int
    session_id: int

    def __post_init__(self) -> None:
        if type(self.client_order_id) is not str or not _ORDER_CLIENT_ID_RE.fullmatch(
            self.client_order_id
        ):
            _reject("invalid_native_client_order_id")
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            _reject("invalid_native_instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            _reject("invalid_native_exchange")
        if type(self.side) is not str or self.side not in _SIDES:
            _reject("invalid_native_side")
        if type(self.quantity) is not int or self.quantity <= 0:
            _reject("invalid_native_quantity")
        object.__setattr__(self, "limit_price", _decimal(self.limit_price, "native_limit_price"))
        if type(self.traded_quantity) is not int or not 0 <= self.traded_quantity <= self.quantity:
            _reject("invalid_native_traded_quantity")
        if type(self.status) is not str or self.status not in (
            frozenset(("OPEN", "PARTIAL")) | _TERMINAL_STATUSES
        ):
            _reject("invalid_native_order_status")
        if type(self.order_ref) is not str or not _ID_RE.fullmatch(self.order_ref):
            _reject("invalid_native_order_ref")
        if type(self.order_sys_id) is not str or not _ID_RE.fullmatch(self.order_sys_id):
            _reject("invalid_native_order_sys_id")
        if type(self.front_id) is not int or self.front_id <= 0:
            _reject("invalid_native_front_id")
        if type(self.session_id) is not int or self.session_id <= 0:
            _reject("invalid_native_session_id")


@dataclass(frozen=True)
class CtpSimulationTradeSnapshot:
    client_order_id: str
    trade_id: str
    quantity: int
    instrument_id: str
    exchange_id: str
    side: str

    def __post_init__(self) -> None:
        if type(self.client_order_id) is not str or not _ORDER_CLIENT_ID_RE.fullmatch(
            self.client_order_id
        ):
            _reject("invalid_native_trade_client_order_id")
        if type(self.trade_id) is not str or not _ID_RE.fullmatch(self.trade_id):
            _reject("invalid_native_trade_id")
        if type(self.quantity) is not int or self.quantity <= 0:
            _reject("invalid_native_trade_quantity")
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            _reject("invalid_native_trade_instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            _reject("invalid_native_trade_exchange")
        if type(self.side) is not str or self.side not in _SIDES:
            _reject("invalid_native_trade_side")


@dataclass(frozen=True)
class CtpSimulationPositionSnapshot:
    instrument_id: str
    exchange_id: str
    side: str
    quantity: int

    def __post_init__(self) -> None:
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            _reject("invalid_native_position_instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            _reject("invalid_native_position_exchange")
        if type(self.side) is not str or self.side not in _SIDES:
            _reject("invalid_native_position_side")
        if type(self.quantity) is not int or self.quantity < 0:
            _reject("invalid_native_position_quantity")


@dataclass(frozen=True)
class CtpSimulationCancelRequestSnapshot:
    """Terminal or unresolved native evidence for one submitted cancel action."""

    action_id: str
    client_order_id: str
    target_order_sys_id: str
    target_order_ref: str
    target_front_id: int
    target_session_id: int
    status: str

    def __post_init__(self) -> None:
        for name in ("action_id", "target_order_sys_id", "target_order_ref"):
            value = getattr(self, name)
            if type(value) is not str or not _ID_RE.fullmatch(value):
                _reject("invalid_native_cancel_request_identity")
        if type(self.client_order_id) is not str or not _ORDER_CLIENT_ID_RE.fullmatch(
            self.client_order_id
        ):
            _reject("invalid_native_cancel_request_identity")
        if type(self.target_front_id) is not int or self.target_front_id <= 0:
            _reject("invalid_native_cancel_front_id")
        if type(self.target_session_id) is not int or self.target_session_id <= 0:
            _reject("invalid_native_cancel_session_id")
        if type(self.status) is not str or self.status not in (
            "PENDING",
            "CANCELED",
            "REJECTED",
            "UNKNOWN",
        ):
            _reject("invalid_native_cancel_request_status")


@dataclass(frozen=True)
class CtpSimulationQueryResult:
    complete: bool
    identity: CtpSimulationSessionIdentity
    records: Tuple[Any, ...]
    # Keep the SDK-owned QueryResult (including its private provenance source)
    # available to a composition-owned verifier.  Flattening it to ``records``
    # would discard request id, filter, generation, and callback evidence.
    native_evidence: Any = field(default=None, repr=False, compare=False)


class CtpSimulationNativePort(Protocol):
    """Small adapter over TraderClient's gated writes and native query APIs."""

    def get_execution_identity(self) -> CtpSimulationSessionIdentity: ...

    def submit_order_insert(
        self, request: CtpSimulationWriteRequest
    ) -> CtpSimulationDispatchReceipt: ...

    def authorize_write(
        self,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
        *,
        action_id: Optional[str] = None,
    ) -> None:
        """Stage the already verified one-shot approval at the native boundary."""
        ...

    def query_orders(self, client_order_id: str) -> CtpSimulationQueryResult: ...

    def query_trades(self, client_order_id: str) -> CtpSimulationQueryResult: ...

    def query_positions(self, instrument_id: str, exchange_id: str) -> CtpSimulationQueryResult: ...

    def query_account_open_orders(self) -> CtpSimulationQueryResult:
        """Return every native open order on the account, across all contracts."""
        ...

    def query_cancel_requests(self, action_ids: Tuple[str, ...]) -> CtpSimulationQueryResult:
        """Return native callback outcomes for every action ID, including unresolved ones."""
        ...

    def submit_order_action(
        self, snapshot: CtpSimulationOrderSnapshot, action_id: str
    ) -> CtpSimulationDispatchReceipt:
        """Submit action with a caller-stable ID for native callback correlation."""
        ...

    def close(self) -> None: ...


class CtpAccountFlowLease:
    """Cross-process exclusive owner of one account's shared CTP flow directory."""

    def __init__(self, account_fingerprint_sha256: str, lock_root: Path) -> None:
        self.account_fingerprint_sha256 = _digest(
            account_fingerprint_sha256, "account_fingerprint_sha256"
        )
        if not isinstance(lock_root, (str, os.PathLike)) or not Path(lock_root).is_absolute():
            _reject("flow_lock_root_must_be_absolute")
        self._root = Path(lock_root)
        self._fd: Optional[int] = None
        self._thread_lock = threading.Lock()

    def acquire(self) -> "CtpAccountFlowLease":
        if self._fd is not None:
            _reject("flow_lease_already_acquired")
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            _reject("flow_lock_root_symlink")
        path = self._root / (self.account_fingerprint_sha256 + ".lock")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags, 0o600)
        try:
            if not os.path.isfile(str(path)) or os.path.islink(str(path)):
                _reject("flow_lock_file_invalid")
            if os.name == "nt":
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except CtpSimulationExecutionError:
            os.close(fd)
            raise
        except OSError:
            os.close(fd)
            _reject("account_flow_already_owned")
        self._fd = fd
        return self

    def assert_held(self, account_fingerprint_sha256: str) -> None:
        if self._fd is None or not hmac.compare_digest(
            self.account_fingerprint_sha256, account_fingerprint_sha256
        ):
            _reject("account_flow_lease_required")

    def release(self) -> None:
        with self._thread_lock:
            fd, self._fd = self._fd, None
            if fd is None:
                return
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            finally:
                os.close(fd)

    def __enter__(self) -> "CtpAccountFlowLease":
        return self.acquire()

    def __exit__(self, *_: Any) -> None:
        self.release()


@dataclass(frozen=True)
class _ExecutionJournalScope:
    runtime_id: str
    account_fingerprint_sha256: str
    config_digest: str
    front_pair_set_sha256: str
    selected_md_front: str
    selected_td_front: str
    profile_digest: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        scope = {
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "config_digest": self.config_digest,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "runtime_id": self.runtime_id,
            "schema_version": _JOURNAL_SCOPE_SCHEMA_VERSION,
            "selected_md_front": self.selected_md_front,
            "selected_td_front": self.selected_td_front,
        }
        if self.profile_digest is not None:
            scope["profile_digest"] = self.profile_digest
        return scope

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


def _execution_journal_scope(
    effective: EffectiveRuntimeConfig,
    registration: CtpSimulationExecutionRegistration,
) -> _ExecutionJournalScope:
    """Bind a journal to the sealed config's ordered candidate set and selection."""

    config = effective.config
    config_digest = config.config_digest
    if registration.config_digest is not None and registration.config_digest != config_digest:
        _reject("execution_journal_config_scope_mismatch")
    profile = effective.profile
    if profile is None:
        if registration.profile_digest is not None or registration.profile_approval_receipt_digest is not None:
            _reject("execution_journal_profile_scope_mismatch")
    elif (
        type(profile) is not RuntimeProfile
        or profile is not registration.runtime_registration.profile_for("simulation", "sandbox")
        or profile.digest != registration.profile_digest
        or profile.approval_receipt_digest != registration.profile_approval_receipt_digest
    ):
        _reject("execution_journal_profile_scope_mismatch")

    selected_pair = (registration.md_front, registration.td_front)
    if profile is not None:
        private = getattr(config, "ctp", None)
        legacy_private = getattr(config, "ctp_simnow", None)
        if (
            type(private) is not CtpPrivateConfig
            or (legacy_private is not None and legacy_private is not private)
        ):
            _reject("execution_journal_canonical_ctp_scope_required")
    else:
        private = getattr(config, "ctp_simnow", None)
        if private is None:
            private = getattr(config, "ctp", None)
    configured_pairs = getattr(private, "front_pairs", None) if private is not None else None
    if configured_pairs is None:
        # Older callers can still use a single explicitly registered pair. New
        # multi-pair selectors always carry their candidate list in the sealed
        # SimNow block and the registration carries its digest.
        front_pairs = (selected_pair,)
    else:
        try:
            front_pairs = tuple(
                (
                    _validate_front(pair["md_front"], "md_front"),
                    _validate_front(pair["td_front"], "td_front"),
                )
                for pair in configured_pairs
            )
        except (KeyError, TypeError):
            _reject("execution_journal_front_pair_set_invalid")
        if not front_pairs or len(set(front_pairs)) != len(front_pairs):
            _reject("execution_journal_front_pair_set_invalid")
    if front_pairs.count(selected_pair) != 1:
        _reject("execution_journal_selected_front_pair_mismatch")
    candidate_digest = _front_pair_set_digest(front_pairs)
    if (
        registration.front_pair_set_sha256 is not None
        and registration.front_pair_set_sha256 != candidate_digest
    ):
        _reject("execution_journal_front_pair_set_mismatch")

    runtime_id = registration.runtime_registration.runtime_id
    if type(runtime_id) is not str or not runtime_id:
        _reject("execution_journal_runtime_scope_invalid")
    return _ExecutionJournalScope(
        runtime_id=runtime_id,
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        config_digest=config_digest,
        front_pair_set_sha256=candidate_digest,
        selected_md_front=registration.md_front,
        selected_td_front=registration.td_front,
        profile_digest=None if profile is None else profile.digest,
    )


_LEGACY_EXECUTION_JOURNAL_TABLES = frozenset(
    {"ctp_sim_orders", "ctp_sim_journal_metadata", "ctp_sim_journal_scopes"}
)
_LEGACY_ORDER_COLUMNS = frozenset(
    {
        "client_order_id",
        "approval_id",
        "request_digest",
        "request_json",
        "state",
        "order_ref",
        "order_sys_id",
        "front_id",
        "session_id",
        "status",
        "traded_quantity",
        "position_digest",
        "updated_at",
    }
)


def _preflight_legacy_execution_journal_path(path: Path) -> None:
    """Reject a foreign SQLite ledger before the legacy journal changes it.

    The new execution Store shares this code-owned file path. Its V19/V20
    schema must never be opened by this journal: even ``PRAGMA
    journal_mode=WAL`` can mutate the file before ``_initialize_schema`` gets a
    chance to notice foreign tables. Only a new empty file or the known narrow
    ``ctp_sim_*`` table signatures may proceed. Unknown, partial, and
    uncertain SQLite states fail closed.
    """

    # Prefer the execution package's public, read-only ledger classifier when
    # the current package exposes it. Older installations can still use the
    # exact legacy SQLite signature check below; no SDK-private SQL is used.
    try:
        from bt_api_execution.store import (
            CtpAccountStoreFileInspection,
            SqliteExecutionStore,
        )
    except Exception:
        CtpAccountStoreFileInspection = None
        SqliteExecutionStore = None
    inspect_file = getattr(SqliteExecutionStore, "inspect_ctp_account_store_file", None)
    if callable(inspect_file):
        try:
            inspection = inspect_file(str(path))
            if type(inspection) is not CtpAccountStoreFileInspection or inspection.kind not in {
                "MISSING",
                "LEGACY_CTP_JOURNAL",
            }:
                _reject("execution_journal_foreign_store")
        except CtpSimulationExecutionError:
            raise
        except Exception:
            # Some older but otherwise recognizable legacy journals (notably
            # a populated orders-only schema) are intentionally rejected by
            # the newer Store classifier because their scope cannot be proven.
            # Continue with this module's exact read-only legacy signature
            # check so it can retain the established, specific
            # ``legacy_scope_missing`` diagnosis without opening SQLite for
            # writing. Any other incomplete or unknown schema still fails in
            # that exact check below.
            pass

    sidecars = (Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    try:
        if not os.path.lexists(str(path)):
            if any(os.path.lexists(str(sidecar)) for sidecar in sidecars):
                _reject("execution_journal_foreign_store")
            return
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            _reject("execution_journal_foreign_store")
        if info.st_size == 0:
            if any(os.path.lexists(str(sidecar)) for sidecar in sidecars):
                _reject("execution_journal_foreign_store")
            return
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2.0)
        try:
            rows = connection.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            tables = {name for object_type, name in rows if object_type == "table"}
            if len(tables) != len(rows) or tables not in (
                {"ctp_sim_orders"},
                _LEGACY_EXECUTION_JOURNAL_TABLES,
            ):
                _reject("execution_journal_foreign_store")
            if "ctp_sim_orders" in tables:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(ctp_sim_orders)")
                }
                if not _LEGACY_ORDER_COLUMNS.issubset(
                    columns
                ) or columns - _LEGACY_ORDER_COLUMNS - {"execution_scope_sha256"}:
                    _reject("execution_journal_foreign_store")
                order_count = int(
                    connection.execute("SELECT COUNT(*) FROM ctp_sim_orders").fetchone()[0]
                )
                if order_count:
                    metadata_count = 0
                    if "ctp_sim_journal_metadata" in tables:
                        metadata_count = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM ctp_sim_journal_metadata WHERE singleton=1"
                            ).fetchone()[0]
                        )
                    if metadata_count != 1:
                        _reject("execution_journal_legacy_scope_missing")
            for table, expected in (
                (
                    "ctp_sim_journal_metadata",
                    {"singleton", "schema_version", "scope_json", "scope_sha256"},
                ),
                ("ctp_sim_journal_scopes", {"scope_sha256", "schema_version", "scope_json"}),
            ):
                if table in tables:
                    columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(" + table + ")")
                    }
                    if columns != expected:
                        _reject("execution_journal_foreign_store")
        finally:
            connection.close()
    except CtpSimulationExecutionError:
        raise
    except Exception:
        _reject("execution_journal_foreign_store")


class _ExecutionJournal:
    def __init__(self, path: Path, scope: _ExecutionJournalScope) -> None:
        if not path.is_absolute():
            _reject("journal_path_must_be_absolute")
        path.parent.mkdir(parents=True, exist_ok=True)
        _preflight_legacy_execution_journal_path(path)
        self._db = sqlite3.connect(str(path), timeout=2.0, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._scope = scope
        self._scope_digest = scope.digest
        try:
            self._initialize_schema()
            # A process can die after native dispatch but before persisting its
            # response. Never retry such an intent automatically.
            self._db.execute(
                "UPDATE ctp_sim_orders SET state='UNKNOWN', updated_at=? WHERE state='DISPATCHING'",
                (time.time(),),
            )
            self._db.commit()
        except BaseException:
            self._db.rollback()
            self._db.close()
            raise
        self._lock = threading.RLock()

    def _initialize_schema(self) -> None:
        """Initialize scope history and permit rollover only after terminal intents."""

        self._db.execute("BEGIN IMMEDIATE")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS ctp_sim_orders (
                client_order_id TEXT PRIMARY KEY,
                approval_id TEXT NOT NULL UNIQUE,
                request_digest TEXT NOT NULL,
                request_json TEXT NOT NULL,
                state TEXT NOT NULL,
                order_ref TEXT,
                order_sys_id TEXT,
                front_id INTEGER,
                session_id INTEGER,
                status TEXT,
                traded_quantity INTEGER NOT NULL DEFAULT 0,
                position_digest TEXT,
                updated_at REAL NOT NULL,
                execution_scope_sha256 TEXT NOT NULL
            )"""
        )
        order_columns = {
            row[1] for row in self._db.execute("PRAGMA table_info(ctp_sim_orders)").fetchall()
        }
        order_count = int(self._db.execute("SELECT COUNT(*) FROM ctp_sim_orders").fetchone()[0])
        if "execution_scope_sha256" not in order_columns:
            if order_count:
                _reject("execution_journal_legacy_scope_missing")
            self._db.execute(
                "ALTER TABLE ctp_sim_orders ADD COLUMN execution_scope_sha256 TEXT"
            )

        self._db.execute(
            """CREATE TABLE IF NOT EXISTS ctp_sim_journal_metadata (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                schema_version INTEGER NOT NULL,
                scope_json TEXT NOT NULL,
                scope_sha256 TEXT NOT NULL
            )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS ctp_sim_journal_scopes (
                scope_sha256 TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                scope_json TEXT NOT NULL
            )"""
        )
        metadata_rows = self._db.execute(
            "SELECT schema_version, scope_json, scope_sha256 "
            "FROM ctp_sim_journal_metadata WHERE singleton=1"
        ).fetchall()
        history_rows = self._db.execute(
            "SELECT scope_sha256, schema_version, scope_json FROM ctp_sim_journal_scopes"
        ).fetchall()
        known_scopes: dict[str, dict[str, Any]] = {}
        for history_digest, history_version, history_json in history_rows:
            try:
                history_scope = json.loads(history_json)
                history_canonical = _canonical(history_scope).decode("ascii")
            except (TypeError, ValueError):
                _reject("execution_journal_metadata_corrupt")
            if (
                history_version != _JOURNAL_SCOPE_SCHEMA_VERSION
                or history_canonical != history_json
                or hashlib.sha256(history_canonical.encode("ascii")).hexdigest()
                != history_digest
                or history_digest in known_scopes
            ):
                _reject("execution_journal_metadata_corrupt")
            known_scopes[history_digest] = history_scope

        if not metadata_rows:
            if order_count:
                _reject("execution_journal_legacy_scope_missing")
            if history_rows:
                _reject("execution_journal_metadata_corrupt")
            scope_json = _canonical(self._scope.as_dict()).decode("ascii")
            self._db.execute(
                "INSERT INTO ctp_sim_journal_scopes(scope_sha256, schema_version, scope_json) "
                "VALUES(?, ?, ?)",
                (self._scope_digest, _JOURNAL_SCOPE_SCHEMA_VERSION, scope_json),
            )
            self._db.execute(
                "INSERT INTO ctp_sim_journal_metadata"
                "(singleton, schema_version, scope_json, scope_sha256) VALUES(1, ?, ?, ?)",
                (_JOURNAL_SCOPE_SCHEMA_VERSION, scope_json, self._scope_digest),
            )
        elif len(metadata_rows) != 1:
            _reject("execution_journal_metadata_corrupt")
        else:
            schema_version, stored_json, stored_digest = metadata_rows[0]
            try:
                stored_scope = json.loads(stored_json)
                stored_canonical = _canonical(stored_scope).decode("ascii")
            except (TypeError, ValueError):
                _reject("execution_journal_metadata_corrupt")
            if stored_canonical != stored_json or hashlib.sha256(
                stored_canonical.encode("ascii")
            ).hexdigest() != stored_digest:
                _reject("execution_journal_metadata_corrupt")
            if schema_version == 1:
                # Version 1 had a single active scope and stamped every row
                # with it. Preserve that history when upgrading the metadata.
                row_scope_mismatch = int(
                    self._db.execute(
                        "SELECT COUNT(*) FROM ctp_sim_orders "
                        "WHERE execution_scope_sha256 IS NULL OR execution_scope_sha256 != ?",
                        (stored_digest,),
                    ).fetchone()[0]
                )
                if row_scope_mismatch:
                    _reject("execution_journal_metadata_corrupt")
                if history_rows:
                    _reject("execution_journal_metadata_corrupt")
                self._db.execute(
                    "INSERT INTO ctp_sim_journal_scopes"
                    "(scope_sha256, schema_version, scope_json) VALUES(?, ?, ?)",
                    (stored_digest, _JOURNAL_SCOPE_SCHEMA_VERSION, stored_json),
                )
                self._db.execute(
                    "UPDATE ctp_sim_journal_metadata SET schema_version=? WHERE singleton=1",
                    (_JOURNAL_SCOPE_SCHEMA_VERSION,),
                )
                schema_version = _JOURNAL_SCOPE_SCHEMA_VERSION
                known_scopes[stored_digest] = stored_scope
            if schema_version != _JOURNAL_SCOPE_SCHEMA_VERSION:
                _reject("execution_journal_schema_unsupported")
            if known_scopes.get(stored_digest) != stored_scope:
                _reject("execution_journal_metadata_corrupt")

            dangling_row_count = int(
                self._db.execute(
                    "SELECT COUNT(*) FROM ctp_sim_orders AS orders "
                    "LEFT JOIN ctp_sim_journal_scopes AS scopes "
                    "ON scopes.scope_sha256=orders.execution_scope_sha256 "
                    "WHERE orders.execution_scope_sha256 IS NULL OR scopes.scope_sha256 IS NULL"
                ).fetchone()[0]
            )
            if dangling_row_count:
                _reject("execution_journal_row_scope_mismatch")

            if stored_digest != self._scope_digest or stored_scope != self._scope.as_dict():
                unresolved_count = int(
                    self._db.execute(
                        "SELECT COUNT(*) FROM ctp_sim_orders WHERE state NOT IN (?, ?, ?, ?)",
                        tuple(sorted(_TERMINAL_JOURNAL_STATES)),
                    ).fetchone()[0]
                )
                if unresolved_count:
                    _reject("execution_journal_scope_mismatch")
                candidate_json = _canonical(self._scope.as_dict()).decode("ascii")
                prior_candidate = known_scopes.get(self._scope_digest)
                if prior_candidate is not None and prior_candidate != self._scope.as_dict():
                    _reject("execution_journal_metadata_corrupt")
                if prior_candidate is None:
                    if len(known_scopes) >= _MAX_JOURNAL_SCOPE_HISTORY:
                        _reject("execution_journal_scope_history_full")
                    self._db.execute(
                        "INSERT INTO ctp_sim_journal_scopes"
                        "(scope_sha256, schema_version, scope_json) VALUES(?, ?, ?)",
                        (
                            self._scope_digest,
                            _JOURNAL_SCOPE_SCHEMA_VERSION,
                            candidate_json,
                        ),
                    )
                self._db.execute(
                    "UPDATE ctp_sim_journal_metadata "
                    "SET schema_version=?, scope_json=?, scope_sha256=? WHERE singleton=1",
                    (
                        _JOURNAL_SCOPE_SCHEMA_VERSION,
                        candidate_json,
                        self._scope_digest,
                    ),
                )

    def states(self) -> Tuple[Tuple[Any, ...], ...]:
        with self._lock:
            return cast(
                Tuple[Tuple[Any, ...], ...],
                tuple(
                    self._db.execute(
                        "SELECT client_order_id, request_digest, request_json, state, order_ref, "
                        "order_sys_id, front_id, session_id, status "
                        "FROM ctp_sim_orders ORDER BY rowid"
                    ).fetchall()
                ),
            )

    def get(self, client_order_id: str) -> Optional[Tuple[Any, ...]]:
        with self._lock:
            return cast(
                Optional[Tuple[Any, ...]],
                self._db.execute(
                    "SELECT client_order_id, approval_id, request_digest, request_json, state, "
                    "order_ref, order_sys_id, front_id, session_id, status, traded_quantity "
                    "FROM ctp_sim_orders "
                    "WHERE client_order_id=?",
                    (client_order_id,),
                ).fetchone(),
            )

    def cancel_rows_for(self, client_order_id: str) -> Tuple[Tuple[Any, ...], ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT client_order_id, approval_id, request_digest, request_json, state "
                "FROM ctp_sim_orders"
            ).fetchall()
        result = []
        for row in rows:
            try:
                payload = json.loads(row[3])
            except (TypeError, ValueError):
                _reject("execution_journal_corrupt")
            if (
                payload.get("action") == "CANCEL"
                and payload.get("client_order_id") == client_order_id
            ):
                result.append(tuple(row))
        return cast(Tuple[Tuple[Any, ...], ...], tuple(result))

    def reserve(
        self,
        request: CtpSimulationWriteRequest,
        approval_id: str,
        *,
        journal_id: Optional[str] = None,
        position_baseline: Optional[dict[str, int]] = None,
    ) -> None:
        stored_id = journal_id or request.client_order_id
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO ctp_sim_orders(client_order_id, approval_id, request_digest, "
                    "request_json, state, updated_at, execution_scope_sha256) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        stored_id,
                        approval_id,
                        request.digest,
                        json.dumps(
                            {
                                "action": request.action,
                                "client_order_id": request.client_order_id,
                                "exchange_id": request.exchange_id,
                                "instrument_id": request.instrument_id,
                                "limit_price": str(request.limit_price),
                                "offset": request.offset,
                                "hedge_flag": request.hedge_flag,
                                "position_baseline": position_baseline,
                                "quantity": request.quantity,
                                "side": request.side,
                                "target_order_sys_id": request.target_order_sys_id,
                                "target_order_ref": request.target_order_ref,
                                "target_front_id": request.target_front_id,
                                "target_session_id": request.target_session_id,
                            },
                            sort_keys=True,
                        ),
                        "DISPATCHING",
                        time.time(),
                        self._scope_digest,
                    ),
                )
                self._db.commit()
            except sqlite3.IntegrityError:
                self._db.rollback()
                _reject("order_or_approval_already_used")

    def set_state(
        self,
        client_order_id: str,
        state: str,
        *,
        snapshot: Optional[CtpSimulationOrderSnapshot] = None,
        position_digest: Optional[str] = None,
    ) -> None:
        with self._lock:
            values = (
                state,
                snapshot.order_ref if snapshot else None,
                snapshot.order_sys_id if snapshot else None,
                snapshot.front_id if snapshot else None,
                snapshot.session_id if snapshot else None,
                snapshot.status if snapshot else None,
                snapshot.traded_quantity if snapshot else 0,
                position_digest,
                time.time(),
                client_order_id,
            )
            self._db.execute(
                "UPDATE ctp_sim_orders SET state=?, order_ref=COALESCE(?,order_ref), "
                "order_sys_id=COALESCE(?,order_sys_id), front_id=COALESCE(?,front_id), "
                "session_id=COALESCE(?,session_id), status=COALESCE(?,status), "
                "traded_quantity=?, position_digest=COALESCE(?,position_digest), updated_at=? "
                "WHERE client_order_id=?",
                values,
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


@dataclass(frozen=True)
class CtpSimulationReconciliation:
    client_order_id: str
    status: str
    traded_quantity: int
    trade_count: int
    position_digest: str
    complete: bool


def _request_from_row(row: Tuple[Any, ...]) -> CtpSimulationWriteRequest:
    payload = json.loads(row[3])
    return CtpSimulationWriteRequest(
        action=payload["action"],
        client_order_id=payload["client_order_id"],
        instrument_id=payload["instrument_id"],
        exchange_id=payload["exchange_id"],
        side=payload["side"],
        quantity=payload["quantity"],
        limit_price=Decimal(payload["limit_price"]),
        offset=payload["offset"],
        hedge_flag=payload["hedge_flag"],
        target_order_sys_id=payload["target_order_sys_id"],
        target_order_ref=payload["target_order_ref"],
        target_front_id=payload["target_front_id"],
        target_session_id=payload["target_session_id"],
    )


class CtpSimulationExecutionSession:
    """Single-account, one-outstanding-order managed execution session."""

    def __init__(
        self,
        registration: CtpSimulationExecutionRegistration,
        native: CtpSimulationNativePort,
        approval_verifier: CtpSimulationApprovalVerifier,
        query_evidence_verifier: CtpSimulationQueryEvidenceVerifier,
        writer_fence: CtpSimulationAccountWriterFence,
        lease: CtpAccountFlowLease,
        journal_path: Path,
        *,
        effective: Optional[EffectiveRuntimeConfig] = None,
        registry: Optional[RuntimeRegistry] = None,
        journal: Optional[_ExecutionJournal] = None,
        journal_scope: Optional[_ExecutionJournalScope] = None,
    ) -> None:
        self.registration = registration
        if registration.profile_digest is not None and (
            type(effective) is not EffectiveRuntimeConfig
            or type(registry) is not RuntimeRegistry
        ):
            _reject("profile_session_admission_context_required")
        self._effective = effective
        self._registry = registry
        self._native = native
        self._verifier = approval_verifier
        self._query_evidence_verifier = query_evidence_verifier
        self._writer_fence = writer_fence
        self._lease = lease
        self._lease.assert_held(registration.account_fingerprint_sha256)
        self._assert_writer_fence()
        self._identity = self._require_identity()
        if journal is not None:
            self._journal = journal
        elif journal_scope is not None:
            self._journal = _ExecutionJournal(journal_path, journal_scope)
        else:
            _reject("execution_journal_scope_required")
        self._lock = threading.RLock()
        # The native adapter only retains cancel callback correlation in
        # memory. A verified terminal order snapshot can recover pending
        # journal intents after a process restart, but never substitute for a
        # callback that should still be available in this process.
        self._volatile_cancel_action_ids: set[str] = set()
        self._state = "OPEN"

    def _assert_writer_fence(self) -> None:
        fence = self._writer_fence
        if (
            getattr(fence, "environment", None) != self.registration.environment
            or getattr(fence, "account_fingerprint_sha256", None)
            != self.registration.account_fingerprint_sha256
            or type(getattr(fence, "fence_id", None)) is not str
            or not _ID_RE.fullmatch(fence.fence_id)
            or not callable(getattr(fence, "assert_active", None))
        ):
            _reject("account_writer_fence_scope_mismatch")
        try:
            fence.assert_active()
        except Exception:
            _reject("account_writer_fence_unavailable")

    def _require_identity(self) -> CtpSimulationSessionIdentity:
        try:
            identity = self._native.get_execution_identity()
        except Exception:
            _reject("native_session_identity_unavailable")
        if type(identity) is not CtpSimulationSessionIdentity:
            _reject("native_session_identity_invalid")
        registration = self.registration
        if (
            identity.environment != registration.environment
            or identity.sdk_profile != registration.sdk_profile
            or identity.td_front != registration.td_front
            or identity.md_front != registration.md_front
            or not hmac.compare_digest(
                identity.account_fingerprint_sha256,
                registration.account_fingerprint_sha256,
            )
            or (identity.native_simnow_managed_mode and identity.native_gate_armed)
            or (not identity.native_simnow_managed_mode and identity.native_gate_armed is not True)
        ):
            _reject("native_session_scope_or_authorization_mode_mismatch")
        return identity

    def _require_open(self) -> CtpSimulationSessionIdentity:
        if self._state != "OPEN":
            _reject("session_poisoned" if self._state == "POISONED" else "session_closed")
        self._lease.assert_held(self.registration.account_fingerprint_sha256)
        self._assert_writer_fence()
        identity = self._require_identity()
        if identity != self._identity:
            _reject("native_session_generation_changed")
        return identity

    def _revalidate_profile_scope(self) -> None:
        """Refresh a profile-backed scope before reserving or dispatching a write."""

        if self.registration.profile_digest is None:
            return
        if (
            type(self._effective) is not EffectiveRuntimeConfig
            or type(self._registry) is not RuntimeRegistry
        ):
            _reject("profile_session_admission_context_required")
        require_ctp_simulation_execution_admission(
            self._effective, self._registry, self.registration
        )

    def _revalidate_profile_scope_after_reserve(self, *journal_ids: str) -> None:
        """Fence a reserved intent as UNKNOWN if its profile scope has gone stale."""

        try:
            self._revalidate_profile_scope()
        except CtpSimulationExecutionError as exc:
            self._mark_unknown(*journal_ids)
            raise CtpSimulationExecutionError(
                "profile_scope_changed_before_dispatch"
            ) from exc

    def _verify_query_evidence(self, query_kind: str, result: CtpSimulationQueryResult) -> None:
        if (
            type(result) is not CtpSimulationQueryResult
            or result.complete is not True
            or type(result.records) is not tuple
            or result.identity != self._identity
        ):
            _reject("native_query_result_incomplete")
        try:
            verified = self._query_evidence_verifier.verify(
                query_kind,
                result,
                expected_identity=self._identity,
                registration_digest=self.registration.digest,
            )
        except Exception:
            verified = False
        if verified is not True:
            _reject("native_query_evidence_unverified")

    def _validate_request(self, request: CtpSimulationWriteRequest) -> None:
        registration = self.registration
        if (
            request.instrument_id != registration.instrument_id
            or request.exchange_id != registration.exchange_id
            or request.side not in registration.allowed_sides
            or request.hedge_flag != registration.hedge_flag
            or request.offset != "OPEN"
        ):
            _reject("order_scope_mismatch")
        if (
            request.quantity > registration.max_quantity
            or request.quantity % registration.quantity_step
        ):
            _reject("quantity_out_of_bounds")
        if (
            request.limit_price < registration.min_price
            or request.limit_price > registration.max_price
            or (request.limit_price / registration.price_tick)
            != (request.limit_price / registration.price_tick).to_integral_value()
        ):
            _reject("price_out_of_bounds")

    def _verify_approval(
        self, request: CtpSimulationWriteRequest, approval: CtpSimulationWriteApproval
    ) -> float:
        now = time.time()
        registration = self.registration
        expected_receipt = (
            registration.profile_approval_receipt_digest
            if registration.profile_digest is not None
            else registration.runtime_registration.approval_receipt_digest
        )
        if (
            type(approval) is not CtpSimulationWriteApproval
            or approval.key_id != registration.approval_key_id
            or approval.registration_digest != registration.digest
            or approval.receipt_digest != expected_receipt
            or approval.account_fingerprint_sha256 != registration.account_fingerprint_sha256
            or approval.environment != registration.environment
            or approval.td_front != registration.td_front
            or approval.md_front != registration.md_front
            or approval.request_digest != request.digest
            or approval.expires_at - approval.issued_at > registration.approval_ttl_seconds
            or approval.issued_at > now + 1.0
            or approval.expires_at <= now
        ):
            _reject("approval_scope_or_expiry_mismatch")
        try:
            valid = self._verifier.verify(approval)
        except Exception:
            valid = False
        if valid is not True:
            _reject("approval_signature_rejected")
        remaining = approval.expires_at - now
        if remaining <= 0:
            _reject("approval_expired")
        return time.monotonic() + remaining

    def _has_unresolved(self) -> bool:
        return any(row[3] in _ORDER_STATES for row in self._journal.states())

    def _position_totals(self, result: CtpSimulationQueryResult) -> dict[str, int]:
        if type(result) is not CtpSimulationQueryResult or result.complete is not True:
            _reject("position_snapshot_incomplete")
        if result.identity != self._identity:
            _reject("position_snapshot_identity_mismatch")
        totals = {"BUY": 0, "SELL": 0}
        for position in result.records:
            if (
                type(position) is not CtpSimulationPositionSnapshot
                or position.instrument_id != self.registration.instrument_id
                or position.exchange_id != self.registration.exchange_id
                or position.side not in _SIDES
                or type(position.quantity) is not int
                or position.quantity < 0
            ):
                _reject("position_snapshot_scope_mismatch")
            totals[position.side] += position.quantity
        return totals

    def _reject_unmanaged_open_orders(self, result: CtpSimulationQueryResult) -> None:
        seen = set()
        for order in result.records:
            if type(order) is not CtpSimulationOrderSnapshot:
                _reject("account_open_order_snapshot_invalid")
            key = (
                order.client_order_id,
                order.order_sys_id,
                order.order_ref,
                order.front_id,
                order.session_id,
            )
            if key in seen:
                _reject("account_open_order_snapshot_ambiguous")
            seen.add(key)
            if (
                order.instrument_id == self.registration.instrument_id
                and order.exchange_id == self.registration.exchange_id
                and order.status not in _TERMINAL_STATUSES
            ):
                _reject("unmanaged_open_order_blocks_submission")

    def _mark_unknown(self, *journal_ids: str) -> None:
        for journal_id in journal_ids:
            self._journal.set_state(journal_id, "UNKNOWN")

    def _verified_cancel_outcomes(
        self,
        cancel_rows: Tuple[Tuple[Any, ...], ...],
        result: CtpSimulationQueryResult,
        order: CtpSimulationOrderSnapshot,
    ) -> dict[str, str]:
        expected_ids = tuple(row[0] for row in cancel_rows)
        records = result.records
        if len(records) != len(expected_ids) or any(
            type(record) is not CtpSimulationCancelRequestSnapshot for record in records
        ):
            _reject("native_cancel_request_readback_incomplete")
        by_id = {record.action_id: record for record in records}
        if len(by_id) != len(records) or set(by_id) != set(expected_ids):
            _reject("native_cancel_request_readback_ambiguous")
        outcomes: dict[str, str] = {}
        for row in cancel_rows:
            action_id = row[0]
            request = _request_from_row(row)
            record = by_id[action_id]
            if (
                record.client_order_id != request.client_order_id
                or record.target_order_sys_id != request.target_order_sys_id
                or record.target_order_ref != request.target_order_ref
                or record.target_front_id != request.target_front_id
                or record.target_session_id != request.target_session_id
            ):
                _reject("native_cancel_request_scope_mismatch")
            if record.status not in ("CANCELED", "REJECTED"):
                _reject("native_cancel_request_outcome_unknown")
            outcomes[action_id] = record.status
        canceled_actions = any(status == "CANCELED" for status in outcomes.values())
        if (order.status == "CANCELED") != canceled_actions:
            _reject("native_cancel_order_action_mismatch")
        return outcomes

    @staticmethod
    def _cancel_target_matches_order(
        row: Tuple[Any, ...], order: CtpSimulationOrderSnapshot
    ) -> bool:
        request = _request_from_row(row)
        return (
            request.action == "CANCEL"
            and request.client_order_id == order.client_order_id
            and request.target_order_sys_id == order.order_sys_id
            and request.target_order_ref == order.order_ref
            and request.target_front_id == order.front_id
            and request.target_session_id == order.session_id
        )

    def _dispatch_outcome(
        self,
        receipt: Any,
        request: CtpSimulationWriteRequest,
        *,
        action_id: Optional[str] = None,
    ) -> str:
        """Accept only a typed receipt bound to this exact request and session."""
        if (
            type(receipt) is not CtpSimulationDispatchReceipt
            or receipt.operation != request.action
            or receipt.request_digest != request.digest
            or receipt.client_order_id != request.client_order_id
            or receipt.action_id != action_id
            or receipt.identity != self._identity
            or receipt.provider_acknowledged is not False
            or (
                receipt.outcome == "QUEUED"
                and (receipt.submit_code != 0 or receipt.local_rejection_verified)
            )
            or (
                receipt.outcome == "REJECTED"
                and (
                    type(receipt.submit_code) is not int
                    or receipt.submit_code >= 0
                    or receipt.local_rejection_verified is not True
                )
            )
            or (
                receipt.outcome == "UNKNOWN" and receipt.local_rejection_verified
            )
        ):
            return "UNKNOWN"
        return receipt.outcome

    def submit_order(
        self,
        *,
        client_order_id: str,
        instrument_id: str,
        exchange_id: str,
        side: str,
        quantity: int,
        limit_price: Decimal,
        approval: CtpSimulationWriteApproval,
    ) -> str:
        request = CtpSimulationWriteRequest(
            action="SUBMIT",
            client_order_id=client_order_id,
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            offset="OPEN",
            hedge_flag=self.registration.hedge_flag,
        )
        with self._lock:
            self._require_open()
            self._validate_request(request)
            if self._has_unresolved():
                _reject("unresolved_order_freezes_new_writes")
            approval_deadline = self._verify_approval(request, approval)
            try:
                self._assert_writer_fence()
                account_open_orders = self._native.query_account_open_orders()
                self._assert_writer_fence()
                position_result = self._native.query_positions(
                    self.registration.instrument_id, self.registration.exchange_id
                )
            except Exception:
                _reject("account_exposure_snapshot_unavailable")
            try:
                self._verify_query_evidence("account_open_orders", account_open_orders)
                self._verify_query_evidence("positions", position_result)
            except Exception:
                _reject("account_exposure_snapshot_unavailable")
            self._reject_unmanaged_open_orders(account_open_orders)
            try:
                position_baseline = self._position_totals(position_result)
            except Exception:
                _reject("account_exposure_snapshot_unavailable")
            if sum(position_baseline.values()) + request.quantity > (
                self.registration.max_gross_position
            ):
                _reject("gross_position_limit_exceeded")
            # Re-read profile-backed config immediately before the durable
            # reservation. A stale scope must not consume an approval or
            # create a dispatch intent.
            self._revalidate_profile_scope()
            self._journal.reserve(
                request, approval.approval_id, position_baseline=position_baseline
            )
            if min(approval.expires_at - time.time(), approval_deadline - time.monotonic()) <= 0:
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("approval_expired_before_dispatch")
            try:
                self._require_open()
            except CtpSimulationExecutionError as exc:
                self._mark_unknown(client_order_id)
                raise CtpSimulationExecutionError(
                    "native_submit_session_changed_before_dispatch"
                ) from exc
            if min(approval.expires_at - time.time(), approval_deadline - time.monotonic()) <= 0:
                self._mark_unknown(client_order_id)
                _reject("approval_expired_before_dispatch")
            self._revalidate_profile_scope_after_reserve(client_order_id)
            try:
                authorize_write = getattr(self._native, "authorize_write", None)
                if callable(authorize_write):
                    authorize_write(request, approval)
                # Authorization may perform blocking external work. Recheck
                # the account fence after it returns so a fence lost during
                # that work cannot still reach the native dispatch call.
                self._assert_writer_fence()
            except Exception:
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_submit_outcome_unknown")
            # Authorization can block while config or profile code changes.
            # Refresh again directly before the native submit call.
            self._revalidate_profile_scope_after_reserve(client_order_id)
            try:
                receipt = self._native.submit_order_insert(request)
                self._require_open()
            except Exception:
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_submit_outcome_unknown")
            outcome = self._dispatch_outcome(receipt, request)
            if outcome == "REJECTED":
                self._journal.set_state(client_order_id, "REJECTED")
                return "REJECTED"
            if outcome != "QUEUED":
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_submit_outcome_unknown")
            self._journal.set_state(client_order_id, "PENDING")
            return "PENDING"

    def cancel_order(self, client_order_id: str, approval: CtpSimulationWriteApproval) -> str:
        with self._lock:
            self._require_open()
            row = self._journal.get(client_order_id)
            if row is None or row[4] not in ("OPEN", "PARTIAL"):
                _reject("cancel_requires_reconciled_open_order")
            original = _request_from_row(row)
            snapshot = CtpSimulationOrderSnapshot(
                client_order_id=client_order_id,
                instrument_id=original.instrument_id,
                exchange_id=original.exchange_id,
                side=original.side,
                quantity=original.quantity,
                limit_price=original.limit_price,
                traded_quantity=int(row[10] or 0),
                status=str(row[9] or "OPEN"),
                order_ref=str(row[5] or ""),
                order_sys_id=str(row[6] or ""),
                front_id=int(row[7] or 0),
                session_id=int(row[8] or 0),
            )
            if (
                not snapshot.order_sys_id
                or not snapshot.order_ref
                or snapshot.front_id <= 0
                or snapshot.session_id <= 0
            ):
                _reject("cancel_native_order_identity_incomplete")
            request = CtpSimulationWriteRequest(
                action="CANCEL",
                client_order_id=client_order_id,
                instrument_id=original.instrument_id,
                exchange_id=original.exchange_id,
                side=original.side,
                quantity=original.quantity,
                limit_price=original.limit_price,
                offset=original.offset,
                hedge_flag=original.hedge_flag,
                target_order_sys_id=snapshot.order_sys_id,
                target_order_ref=snapshot.order_ref,
                target_front_id=snapshot.front_id,
                target_session_id=snapshot.session_id,
            )
            self._validate_request(request)
            approval_deadline = self._verify_approval(request, approval)
            cancel_journal_id = (
                "cancel-"
                + hashlib.sha256(
                    (client_order_id + "\0" + approval.approval_id).encode("ascii")
                ).hexdigest()[:48]
            )
            try:
                self._revalidate_profile_scope()
            except CtpSimulationExecutionError:
                # The original order was reconciled under an obsolete scope;
                # keep it fenced even though no cancel intent was reserved.
                self._journal.set_state(client_order_id, "UNKNOWN")
                raise
            self._journal.reserve(
                request,
                approval.approval_id,
                journal_id=cancel_journal_id,
            )
            if min(approval.expires_at - time.time(), approval_deadline - time.monotonic()) <= 0:
                self._journal.set_state(cancel_journal_id, "REJECTED")
                _reject("approval_expired_before_dispatch")
            try:
                self._require_open()
            except CtpSimulationExecutionError as exc:
                self._mark_unknown(cancel_journal_id, client_order_id)
                raise CtpSimulationExecutionError(
                    "native_cancel_session_changed_before_dispatch"
                ) from exc
            if min(approval.expires_at - time.time(), approval_deadline - time.monotonic()) <= 0:
                self._mark_unknown(cancel_journal_id, client_order_id)
                _reject("approval_expired_before_dispatch")
            self._volatile_cancel_action_ids.add(cancel_journal_id)
            self._revalidate_profile_scope_after_reserve(
                cancel_journal_id, client_order_id
            )
            try:
                authorize_write = getattr(self._native, "authorize_write", None)
                if callable(authorize_write):
                    authorize_write(request, approval, action_id=cancel_journal_id)
                # Keep cancel dispatch behind the same post-authorization
                # fence check as submit dispatch.
                self._assert_writer_fence()
            except Exception:
                # Freeze the original target too; no cancel outcome is known.
                self._journal.set_state(cancel_journal_id, "UNKNOWN")
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_cancel_outcome_unknown")
            self._revalidate_profile_scope_after_reserve(
                cancel_journal_id, client_order_id
            )
            try:
                receipt = self._native.submit_order_action(snapshot, cancel_journal_id)
                self._require_open()
            except Exception:
                # Freeze the original target too; the cancel may have reached CTP.
                self._journal.set_state(cancel_journal_id, "UNKNOWN")
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_cancel_outcome_unknown")
            outcome = self._dispatch_outcome(
                receipt, request, action_id=cancel_journal_id
            )
            if outcome == "REJECTED":
                self._journal.set_state(cancel_journal_id, "REJECTED")
                return "REJECTED"
            if outcome != "QUEUED":
                # The action may have reached CTP even if the receipt is
                # malformed, stale, or bound to another managed intent.
                self._journal.set_state(cancel_journal_id, "UNKNOWN")
                self._journal.set_state(client_order_id, "UNKNOWN")
                _reject("native_cancel_outcome_unknown")
            self._journal.set_state(cancel_journal_id, "CANCEL_PENDING")
            self._journal.set_state(client_order_id, "CANCEL_PENDING")
            return "CANCEL_PENDING"

    def reconcile(self, client_order_id: str) -> CtpSimulationReconciliation:
        with self._lock:
            self._require_open()
            row = self._journal.get(client_order_id)
            if row is None:
                _reject("order_not_journaled")
            request = _request_from_row(row)
            cancel_rows = tuple(
                cancel_row
                for cancel_row in self._journal.cancel_rows_for(client_order_id)
                if cancel_row[4] in _PENDING_CANCEL_STATES
            )
            cancel_ids = tuple(cancel_row[0] for cancel_row in cancel_rows)
            try:
                self._assert_writer_fence()
                orders = self._native.query_orders(client_order_id)
                self._assert_writer_fence()
                trades = self._native.query_trades(client_order_id)
                self._assert_writer_fence()
                positions = self._native.query_positions(
                    self.registration.instrument_id, self.registration.exchange_id
                )
                self._verify_query_evidence("orders", orders)
                self._verify_query_evidence("trades", trades)
                self._verify_query_evidence("positions", positions)
            except Exception:
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_reconciliation_incomplete")
            cancel_requests = None
            cancel_history_verified = False
            cancel_history_absent = False
            if cancel_ids:
                try:
                    self._assert_writer_fence()
                    cancel_requests = self._native.query_cancel_requests(cancel_ids)
                    if (
                        type(cancel_requests) is CtpSimulationQueryResult
                        and cancel_requests.complete is False
                        and cancel_requests.identity == self._identity
                        and type(cancel_requests.records) is tuple
                        and cancel_requests.records == ()
                    ):
                        # TraderClient's action callback history is volatile.
                        # An explicit empty/incomplete result means it has no
                        # local correlation for these intents; it is not
                        # evidence that a cancel request was accepted.
                        cancel_history_absent = True
                    else:
                        self._verify_query_evidence("cancel_requests", cancel_requests)
                        cancel_history_verified = True
                except Exception:
                    # Keep the distinction between absent volatile history
                    # and failed or untrusted evidence. Only the former can
                    # use the terminal-target recovery below.
                    pass
            if (
                len(orders.records) != 1
                or type(orders.records[0]) is not CtpSimulationOrderSnapshot
            ):
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_order_readback_ambiguous")
            snapshot = orders.records[0]
            if (
                snapshot.client_order_id != client_order_id
                or snapshot.instrument_id != request.instrument_id
                or snapshot.exchange_id != request.exchange_id
                or snapshot.side != request.side
                or snapshot.quantity != request.quantity
                or _decimal(snapshot.limit_price, "native_order_limit_price") != request.limit_price
                or type(snapshot.traded_quantity) is not int
                or not 0 <= snapshot.traded_quantity <= request.quantity
                or snapshot.status not in frozenset(("OPEN", "PARTIAL")) | _TERMINAL_STATUSES
                or not snapshot.order_ref
                or not snapshot.order_sys_id
            ):
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_order_readback_mismatch")
            if any(type(trade) is not CtpSimulationTradeSnapshot for trade in trades.records):
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_trade_readback_invalid")
            trade_ids = [trade.trade_id for trade in trades.records]
            if (
                len(set(trade_ids)) != len(trade_ids)
                or any(
                    trade.client_order_id != client_order_id
                    or trade.instrument_id != request.instrument_id
                    or trade.exchange_id != request.exchange_id
                    or trade.side != request.side
                    or type(trade.quantity) is not int
                    or trade.quantity <= 0
                    for trade in trades.records
                )
                or sum(trade.quantity for trade in trades.records) != snapshot.traded_quantity
            ):
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_trade_volume_mismatch")
            try:
                position_totals = self._position_totals(positions)
            except CtpSimulationExecutionError:
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("native_position_readback_mismatch")
            payload = json.loads(row[3])
            baseline = payload.get("position_baseline")
            if (
                type(baseline) is not dict
                or set(baseline) != _SIDES
                or any(type(value) is not int or value < 0 for value in baseline.values())
            ):
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("position_baseline_missing")
            expected_positions = dict(baseline)
            if request.action == "SUBMIT":
                expected_positions[request.side] += snapshot.traded_quantity
            if position_totals != expected_positions:
                self._mark_unknown(client_order_id, *cancel_ids)
                _reject("position_delta_mismatch")
            state = snapshot.status
            cancel_outcomes = {}
            if cancel_rows:
                if cancel_history_verified:
                    try:
                        cancel_outcomes = self._verified_cancel_outcomes(
                            cancel_rows, cancel_requests, snapshot
                        )
                    except CtpSimulationExecutionError:
                        self._mark_unknown(client_order_id, *cancel_ids)
                        _reject("native_cancel_request_outcome_unverified")
                elif (
                    cancel_history_absent
                    and snapshot.status == "CANCELED"
                    and not any(
                        cancel_id in self._volatile_cancel_action_ids for cancel_id in cancel_ids
                    )
                    and all(
                        self._cancel_target_matches_order(cancel_row, snapshot)
                        for cancel_row in cancel_rows
                    )
                ):
                    # The order, trades and positions above are independently
                    # verified and identify the exact canceled target. Record
                    # that terminal target fact without claiming any cancel
                    # request callback or acceptance.
                    cancel_outcomes = dict.fromkeys(cancel_ids, "TARGET_TERMINAL")
                else:
                    self._mark_unknown(client_order_id, *cancel_ids)
                    _reject("native_cancel_request_outcome_unverified")
            position_digest = hashlib.sha256(
                _canonical(
                    {
                        "BUY": position_totals["BUY"],
                        "SELL": position_totals["SELL"],
                    }
                )
            ).hexdigest()
            self._journal.set_state(
                client_order_id,
                state,
                snapshot=snapshot,
                position_digest=position_digest,
            )
            for cancel_id, cancel_state in cancel_outcomes.items():
                self._journal.set_state(cancel_id, cancel_state)
            return CtpSimulationReconciliation(
                client_order_id=client_order_id,
                status=state,
                traded_quantity=snapshot.traded_quantity,
                trade_count=len(trades.records),
                position_digest=position_digest,
                complete=True,
            )

    def close(self) -> None:
        with self._lock:
            if self._state == "CLOSED":
                return
            if self._state == "POISONED":
                _reject("session_poisoned")
            self._state = "CLOSING"
            failures = []
            pending_base_exception: Optional[BaseException] = None
            try:
                self._native.close()
            except BaseException as exc:
                failures.append("native session")
                if not isinstance(exc, Exception):
                    pending_base_exception = exc
            try:
                self._journal.close()
            except BaseException as exc:
                failures.append("execution journal")
                if pending_base_exception is None and not isinstance(exc, Exception):
                    pending_base_exception = exc
            if failures:
                self._state = "POISONED"
                _retain_poisoned_lease(self._lease)
                if pending_base_exception is not None:
                    raise pending_base_exception
                _reject(
                    "execution_close_failed",
                    "Execution cleanup failed for: "
                    + ", ".join(failures)
                    + "; the owner is poisoned and its flow lease is retained until process exit",
                )
            try:
                self._lease.release()
            except BaseException as exc:
                self._state = "POISONED"
                _retain_poisoned_lease(self._lease)
                if not isinstance(exc, Exception):
                    raise
                _reject(
                    "execution_close_failed",
                    "Account flow lease release failed; the owner is poisoned",
                )
            self._state = "CLOSED"

    def __enter__(self) -> "CtpSimulationExecutionSession":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def open_ctp_simulation_execution(
    *,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: CtpSimulationExecutionRegistration,
    native_session_factory: Callable[
        [CtpSimulationExecutionRegistration, CtpAccountFlowLease], CtpSimulationNativePort
    ],
    approval_verifier: CtpSimulationApprovalVerifier,
    query_evidence_verifier: CtpSimulationQueryEvidenceVerifier,
    writer_fence: CtpSimulationAccountWriterFence,
) -> CtpSimulationExecutionSession:
    """Open one explicitly supplied native session after admission and account lock."""

    require_ctp_simulation_execution_admission(effective, registry, registration)
    journal_scope = _execution_journal_scope(effective, registration)
    if not callable(native_session_factory):
        _reject("native_session_factory_required")
    if not callable(getattr(approval_verifier, "verify", None)):
        _reject("approval_verifier_required")
    if not callable(getattr(query_evidence_verifier, "verify", None)):
        _reject("query_evidence_verifier_required")
    if (
        getattr(writer_fence, "environment", None) != registration.environment
        or getattr(writer_fence, "account_fingerprint_sha256", None)
        != registration.account_fingerprint_sha256
        or type(getattr(writer_fence, "fence_id", None)) is not str
        or not _ID_RE.fullmatch(writer_fence.fence_id)
        or not callable(getattr(writer_fence, "assert_active", None))
    ):
        _reject("account_writer_fence_scope_mismatch")
    try:
        writer_fence.assert_active()
    except Exception:
        _reject("account_writer_fence_unavailable")
    state_root = _prepare_state_root()
    lease = CtpAccountFlowLease(
        registration.account_fingerprint_sha256, state_root / "flow-locks"
    ).acquire()
    journal_path = state_root / "journals" / (registration.account_fingerprint_sha256 + ".sqlite3")
    native = None
    journal: Optional[_ExecutionJournal] = None
    try:
        # Scope validation and safe empty-legacy migration happen under the
        # account lease and before credentials, SDK import or client creation.
        require_ctp_simulation_execution_admission(effective, registry, registration)
        journal_scope = _execution_journal_scope(effective, registration)
        journal = _ExecutionJournal(journal_path, journal_scope)
        # The lock is acquired before this call.  SDK TraderClient currently
        # derives its TD flow directory from broker/user, so every writer for
        # this account must use this owner lease until SDK flow paths are
        # independently unique.
        require_ctp_simulation_execution_admission(effective, registry, registration)
        native = native_session_factory(registration, lease)
        writer_fence.assert_active()
        session = CtpSimulationExecutionSession(
            registration,
            native,
            approval_verifier,
            query_evidence_verifier,
            writer_fence,
            lease,
            journal_path,
            effective=effective,
            registry=registry,
            journal=journal,
        )
        journal = None  # ownership transferred to the returned session
        return session
    except BaseException as open_error:
        cleanup_failures = []
        native_close_failed = False
        native_close_base_exception: Optional[BaseException] = None
        try:
            if journal is not None:
                try:
                    journal.close()
                except BaseException as exc:
                    cleanup_failures.append("execution journal")
                    if not isinstance(exc, Exception):
                        raise
            if native is not None:
                try:
                    native.close()
                except BaseException as exc:
                    native_close_failed = True
                    cleanup_failures.append("native session")
                    if not isinstance(exc, Exception):
                        native_close_base_exception = exc
        finally:
            if native_close_failed:
                _retain_poisoned_lease(lease)
            else:
                try:
                    lease.release()
                except BaseException as exc:
                    cleanup_failures.append("account flow lease")
                    if not isinstance(exc, Exception):
                        raise
        if cleanup_failures:
            if native_close_base_exception is not None:
                raise native_close_base_exception from open_error
            error = CtpSimulationExecutionError(
                "execution_open_cleanup_failed",
                "Execution open cleanup failed for: "
                + ", ".join(cleanup_failures)
                + (
                    "; the owner is poisoned and its flow lease is retained until process exit"
                    if native_close_failed
                    else ""
                ),
            )
            raise error from open_error
        raise


__all__ = [
    "CtpAccountFlowLease",
    "CtpSimulationApprovalVerifier",
    "CtpSimulationAccountWriterFence",
    "CtpSimulationExecutionError",
    "CtpSimulationExecutionRegistration",
    "CtpSimulationExecutionSession",
    "CtpSimulationDispatchReceipt",
    "CtpSimulationOrderSnapshot",
    "CtpSimulationPositionSnapshot",
    "CtpSimulationQueryResult",
    "CtpSimulationQueryEvidenceVerifier",
    "CtpSimulationReconciliation",
    "CtpSimulationSessionIdentity",
    "CtpSimulationTradeSnapshot",
    "CtpSimulationWriteApproval",
    "CtpSimulationWriteRequest",
    "HmacCtpSimulationApprovalVerifier",
    "open_ctp_simulation_execution",
    "require_ctp_simulation_execution_admission",
]
