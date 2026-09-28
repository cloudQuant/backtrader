"""Non-authorizing scope contract for a future bounded CTP production writer.

This module binds a code-owned production execution registration to the sealed
production ``config.yaml`` and trusted runtime registry. It does not resolve
credentials, verify installed SDK artifacts or receipts, import an SDK, create a
provider session, or grant any write authority. The current default inventory
does not contain a registration of this type.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from .config import (
    CtpPrivateConfig,
    CtpProductionPrivateConfig,
    RuntimeConfig,
    require_loaded_runtime_config_seal,
)
from .ctp_production_readonly_admission import production_account_binding_sha256
from .errors import RuntimeConfigError
from .policy import MANAGED_WRITE_CAPABILITIES
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCTION_ID_RE = re.compile(r"^ctp-production:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_HEDGE_FLAGS = frozenset(("1", "2", "3"))
_SIDES = frozenset(("BUY", "SELL"))
_PRODUCTION_ENVIRONMENT = "production"
_SECRETS_REF = "config_yaml"
_EXECUTION_REGISTRATION_SEALS: Dict[int, Tuple[Any, str]] = {}


class CtpProductionExecutionAdmissionError(ValueError):
    """Redacted fail-closed rejection for a production execution scope."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpProductionExecutionAdmissionError(reason, message)


def _require_digest(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_registration", "invalid {0}".format(name))
    return value


def _require_production_identity(value: Any, name: str) -> str:
    if type(value) is not str or _PRODUCTION_ID_RE.fullmatch(value) is None:
        _reject(
            "invalid_registration",
            "{0} must use the CTP production identity namespace".format(name),
        )
    return value


def _front_pair_digest(md_front: str, td_front: str) -> str:
    return hashlib.sha256(
        b"backtrader-ctp-production-front-pair-v1\0" + _canonical([md_front, td_front])
    ).hexdigest()


def _scope_identity_digest(
    *,
    config_digest: str,
    effective_digest: Optional[str],
    registration_digest: str,
    account_binding_sha256: str,
    instrument_id: str,
    exchange_id: str,
    hedge_flag: str,
    front_pair_set_sha256: str,
    front_pair_sha256: str,
) -> str:
    """Return non-authorizing identity metadata for one resolved scope."""

    return hashlib.sha256(
        b"backtrader-ctp-production-config-scope-identity-v1\0"
        + _canonical(
            {
                "account_binding_sha256": account_binding_sha256,
                "config_digest": config_digest,
                "effective_digest": effective_digest,
                "exchange_id": exchange_id,
                "front_pair_sha256": front_pair_sha256,
                "front_pair_set_sha256": front_pair_set_sha256,
                "hedge_flag": hedge_flag,
                "instrument_id": instrument_id,
                "registration_digest": registration_digest,
            }
        )
    ).hexdigest()


def production_front_pair_set_sha256(front_pairs: Any) -> str:
    """Digest an ordered, code-approved production front-pair candidate set.

    This helper only binds approval metadata to explicit configured values. It
    never probes or selects an endpoint.
    """

    if type(front_pairs) not in (tuple, list) or not 1 <= len(front_pairs) <= 8:
        _reject("invalid_registration", "invalid approved production front-pair set")
    normalized = []
    for pair in front_pairs:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            _reject("invalid_registration", "invalid approved production front-pair set")
        md_front, td_front = pair
        for value in (md_front, td_front):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 128
                or any(character.isspace() or ord(character) < 0x20 for character in value)
            ):
                _reject("invalid_registration", "invalid approved production front pair")
        normalized.append((md_front, td_front))
    if len(set(normalized)) != len(normalized):
        _reject("invalid_registration", "approved production front-pair set has duplicates")
    return hashlib.sha256(
        b"backtrader-ctp-production-front-pair-set-v1\0" + _canonical(normalized)
    ).hexdigest()


def _require_decimal(value: Any, name: str, *, positive: bool = True) -> Decimal:
    if type(value) not in (str, int, float, Decimal):
        _reject("invalid_order_limits", "invalid {0}".format(name))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _reject("invalid_order_limits", "invalid {0}".format(name))
    if not result.is_finite() or (positive and result <= 0):
        _reject("invalid_order_limits", "invalid {0}".format(name))
    return result


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _execution_registration_payload(
    registration: "CtpProductionExecutionRegistration",
) -> dict[str, Any]:
    runtime = registration.runtime_registration
    return {
        "account_binding_sha256": registration.account_binding_sha256,
        "allowed_offsets": registration.allowed_offsets,
        "allowed_sides": registration.allowed_sides,
        "approval_receipt_id": registration.approval_receipt_id,
        "approval_receipt_sha256": registration.approval_receipt_sha256,
        "artifact_id": registration.artifact_id,
        "artifact_sha256": registration.artifact_sha256,
        "approved_front_pair_set_sha256": registration.approved_front_pair_set_sha256,
        "environment": registration.environment,
        "exchange_id": registration.exchange_id,
        "hedge_flag": registration.hedge_flag,
        "instrument_id": registration.instrument_id,
        "max_gross_position": registration.max_gross_position,
        "max_order_notional": str(registration.max_order_notional),
        "max_order_quantity": registration.max_order_quantity,
        "max_price": str(registration.max_price),
        "md_front": registration.md_front,
        "min_price": str(registration.min_price),
        "price_tick": str(registration.price_tick),
        "quantity_step": registration.quantity_step,
        "runtime_registration_digest": runtime.digest,
        "runtime_dir": str(runtime.runtime_dir),
        "runtime_id": runtime.runtime_id,
        "strategy_id": runtime.strategy_id,
        "scope_binding_mode": registration.scope_binding_mode,
        "td_front": registration.td_front,
    }


def _payload_digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _seal_registration(registration: "CtpProductionExecutionRegistration") -> None:
    identifier = id(registration)

    def discard(reference: Any) -> None:
        current = _EXECUTION_REGISTRATION_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _EXECUTION_REGISTRATION_SEALS.pop(identifier, None)

    reference = weakref.ref(registration, discard)
    _EXECUTION_REGISTRATION_SEALS[identifier] = (
        reference,
        _payload_digest(_execution_registration_payload(registration)),
    )


def _require_registration_seal(registration: "CtpProductionExecutionRegistration") -> None:
    current = _EXECUTION_REGISTRATION_SEALS.get(id(registration))
    if current is None or current[0]() is not registration:
        _reject("registration_provenance_invalid", "production registration was not sealed")
    try:
        digest = _payload_digest(_execution_registration_payload(registration))
    except CtpProductionExecutionAdmissionError:
        raise
    except Exception:
        _reject("registration_provenance_invalid", "production registration is invalid")
    if digest != current[1]:
        _reject("registration_provenance_invalid", "production registration changed after sealing")


@dataclass(frozen=True)
class CtpProductionExecutionRegistration:
    """Code-owned bounds and production-only receipt/artifact identities.

    Receipt and artifact identities use the ``ctp-production:`` namespace and
    are independent values. They are identity bindings only: this contract
    does not verify a receipt signature or prove that an installed artifact
    matches the digest. The initial supported order envelope is opening limit
    orders with exact cancellation; close offsets are rejected.
    """

    runtime_registration: RegisteredRuntime
    environment: str
    account_binding_sha256: Optional[str] = field(repr=False)
    md_front: Optional[str] = field(repr=False)
    td_front: Optional[str] = field(repr=False)
    instrument_id: Optional[str]
    exchange_id: Optional[str]
    hedge_flag: Optional[str]
    approval_receipt_id: str
    approval_receipt_sha256: str
    artifact_id: str
    artifact_sha256: str
    allowed_sides: Tuple[str, ...]
    allowed_offsets: Tuple[str, ...]
    quantity_step: int
    max_order_quantity: int
    max_gross_position: int
    min_price: Decimal
    max_price: Decimal
    price_tick: Decimal
    max_order_notional: Decimal
    approved_front_pair_set_sha256: Optional[str] = field(default=None, repr=False)
    scope_binding_mode: str = "pinned"

    def __post_init__(self) -> None:
        if type(self.runtime_registration) is not RegisteredRuntime:
            _reject("invalid_registration", "invalid registered runtime binding")
        if self.environment != _PRODUCTION_ENVIRONMENT:
            _reject("environment_mismatch", "CTP production requires environment=production")
        if self.scope_binding_mode not in ("pinned", "sealed_config"):
            _reject("invalid_registration", "invalid production scope binding mode")
        if self.scope_binding_mode == "sealed_config":
            if any(
                value is not None
                for value in (
                    self.account_binding_sha256,
                    self.md_front,
                    self.td_front,
                    self.instrument_id,
                    self.exchange_id,
                    self.hedge_flag,
                    self.approved_front_pair_set_sha256,
                )
            ):
                _reject(
                    "invalid_registration",
                    "sealed-config scope cannot also contain pinned CTP selectors",
                )
        else:
            _require_digest(self.account_binding_sha256, "account_binding_sha256")
        _require_digest(self.approval_receipt_sha256, "approval_receipt_sha256")
        _require_digest(self.artifact_sha256, "artifact_sha256")
        _require_production_identity(self.approval_receipt_id, "approval_receipt_id")
        _require_production_identity(self.artifact_id, "artifact_id")
        if self.approval_receipt_id == self.artifact_id:
            _reject("invalid_registration", "receipt and artifact identities must be distinct")
        if self.approval_receipt_sha256 == self.artifact_sha256:
            _reject("invalid_registration", "receipt and artifact digests must be distinct")

        if self.scope_binding_mode == "pinned" and (self.md_front is None) != (
            self.td_front is None
        ):
            _reject(
                "invalid_registration", "production exact fronts must be both set or both absent"
            )
        if self.scope_binding_mode == "pinned" and self.md_front is None:
            _require_digest(self.approved_front_pair_set_sha256, "approved_front_pair_set_sha256")
        elif (
            self.scope_binding_mode == "pinned" and self.approved_front_pair_set_sha256 is not None
        ):
            _reject("invalid_registration", "production exact fronts cannot also pin a front set")
        for name in ("md_front", "td_front"):
            value = getattr(self, name)
            if value is None:
                continue
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 128
                or any(character.isspace() or ord(character) < 0x20 for character in value)
            ):
                _reject("invalid_registration", "invalid CTP production front pair")
        for name, pattern in (
            ("instrument_id", _INSTRUMENT_RE),
            ("exchange_id", _EXCHANGE_RE),
        ):
            value = getattr(self, name)
            if self.scope_binding_mode == "sealed_config":
                continue
            if type(value) is not str or value != value.strip() or pattern.fullmatch(value) is None:
                _reject("invalid_registration", "invalid production {0}".format(name))
        if self.scope_binding_mode == "pinned" and (
            type(self.hedge_flag) is not str or self.hedge_flag not in _HEDGE_FLAGS
        ):
            _reject("invalid_registration", "invalid production hedge_flag")

        if (
            type(self.allowed_sides) is not tuple
            or not self.allowed_sides
            or any(type(side) is not str or side not in _SIDES for side in self.allowed_sides)
            or len(set(self.allowed_sides)) != len(self.allowed_sides)
        ):
            _reject("invalid_order_limits", "allowed_sides must be a unique BUY/SELL tuple")
        if self.allowed_offsets != ("OPEN",):
            _reject("unsupported_order_offsets", "the bounded production slice supports OPEN only")
        for name in ("quantity_step", "max_order_quantity", "max_gross_position"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                _reject("invalid_order_limits", "invalid {0}".format(name))
        if (
            self.max_order_quantity % self.quantity_step != 0
            or self.max_gross_position % self.quantity_step != 0
            or self.max_gross_position < self.max_order_quantity
        ):
            _reject("invalid_order_limits", "quantity limits are inconsistent")

        min_price = _require_decimal(self.min_price, "min_price")
        max_price = _require_decimal(self.max_price, "max_price")
        price_tick = _require_decimal(self.price_tick, "price_tick")
        max_notional = _require_decimal(self.max_order_notional, "max_order_notional")
        if max_price < min_price:
            _reject("invalid_order_limits", "max_price must not be below min_price")
        if min_price % price_tick or max_price % price_tick:
            _reject("invalid_order_limits", "price bounds must align to price_tick")
        if max_notional < min_price * min(self.quantity_step, self.max_order_quantity):
            _reject("invalid_order_limits", "max_order_notional is below the minimum order value")
        object.__setattr__(self, "min_price", min_price)
        object.__setattr__(self, "max_price", max_price)
        object.__setattr__(self, "price_tick", price_tick)
        object.__setattr__(self, "max_order_notional", max_notional)
        _seal_registration(self)

    @property
    def digest(self) -> str:
        """Return a production-domain-separated digest of reviewed scope data."""

        return hashlib.sha256(
            b"backtrader-ctp-production-execution-registration-v1\0"
            + _canonical(_execution_registration_payload(self))
        ).hexdigest()


@dataclass(frozen=True)
class CtpProductionExecutionConfigBinding:
    """Redacted contract evidence; every provider and execution authority is false."""

    runtime_id: str
    strategy_id: str
    config_digest: str
    effective_digest: Optional[str]
    runtime_registration_digest: str
    registration_digest: str
    scope_identity_sha256: str
    environment: str
    md_front: Optional[str] = field(repr=False)
    td_front: Optional[str] = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    account_binding_sha256: str = field(repr=False)
    approval_receipt_id: str
    approval_receipt_sha256: str
    artifact_id: str
    artifact_sha256: str
    allowed_sides: Tuple[str, ...]
    allowed_offsets: Tuple[str, ...]
    quantity_step: int
    max_order_quantity: int
    max_gross_position: int
    min_price: Decimal
    max_price: Decimal
    price_tick: Decimal
    max_order_notional: Decimal
    front_pair_sha256: str
    front_pair_set_sha256: str
    front_pairs: Tuple[Tuple[str, str], ...] = field(repr=False)
    selected_front_index: Optional[int]
    contract_verified: bool = field(default=True, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)

    def __bool__(self) -> bool:
        raise TypeError("CtpProductionExecutionConfigBinding is non-authorizing contract evidence")

    def as_public_dict(self) -> dict[str, Any]:
        """Return bounded non-secret identity and limits without fronts/account values."""

        return {
            "account_scope": "redacted",
            "allowed_offsets": self.allowed_offsets,
            "allowed_sides": self.allowed_sides,
            "approval_receipt_id": self.approval_receipt_id,
            "approval_receipt_sha256": self.approval_receipt_sha256,
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "config_digest": self.config_digest,
            "contract_verified": self.contract_verified,
            "credential_access_authorized": self.credential_access_authorized,
            "environment": self.environment,
            "effective_digest": self.effective_digest,
            "exchange_id": self.exchange_id,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "front_pair_sha256": self.front_pair_sha256,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "max_gross_position": self.max_gross_position,
            "max_order_notional": str(self.max_order_notional),
            "max_order_quantity": self.max_order_quantity,
            "max_price": str(self.max_price),
            "min_price": str(self.min_price),
            "order_submission_authorized": self.order_submission_authorized,
            "price_tick": str(self.price_tick),
            "provider": "ctp",
            "provider_access_authorized": self.provider_access_authorized,
            "quantity_step": self.quantity_step,
            "registration_digest": self.registration_digest,
            "runtime_id": self.runtime_id,
            "runtime_registration_digest": self.runtime_registration_digest,
            "strategy_id": self.strategy_id,
            "selected_front_index": self.selected_front_index,
            "scope_identity_sha256": self.scope_identity_sha256,
        }


def require_ctp_production_execution_config_binding(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    *,
    selected_front_pair: Optional[Tuple[str, str]] = None,
    effective_runtime: Optional[EffectiveRuntimeConfig] = None,
) -> CtpProductionExecutionConfigBinding:
    """Bind production config and order limits without granting authority.

    The caller must supply the exact code-owned production registration. The
    loaded config must be sealed to ``registry``. ``scope_binding_mode`` may
    be ``sealed_config`` for the canonical live ``ctp:`` block; in that mode
    account, contract, and ordered front candidates are derived from the
    sealed config and the registration contains only code-owned policy and
    risk limits. A profile-scoped registration additionally requires the
    exact sealed ``live/managed_live_direct`` profile, with its narrow CTP
    production policy, selected for this exact config and registry. The
    effective runtime may be omitted only for the legacy global registration
    path.

    The returned scope identity is metadata for a separate approval verifier.
    This function does not verify receipts, keys, signatures, credential ACLs,
    or installed artifact provenance and never authorizes writes. A digest
    change can support stale-receipt rejection only when that external
    verifier actually binds its verified receipt to this identity. A
    multi-pair config remains unresolved until ``selected_front_pair`` is
    supplied by the config-only TCP selector in the production composition.
    """

    if type(config) is not RuntimeConfig:
        _reject("config_required", "a loader-produced production RuntimeConfig is required")
    if type(registry) is not RuntimeRegistry or registry.trusted is not True:
        _reject("registry_required", "a trusted runtime registry is required")
    if type(admission_registration) is not CtpProductionExecutionRegistration:
        _reject(
            "registration_required",
            "a code-owned CTP production execution registration is required",
        )
    _require_registration_seal(admission_registration)

    try:
        require_loaded_runtime_config_seal(config, registry)
    except RuntimeConfigError:
        _reject("config_provenance_invalid", "runtime config does not match its registry seal")
    except Exception:
        _reject("config_provenance_invalid", "runtime config does not match its registry seal")

    try:
        registered = registry.require_runtime_dir(config.strategy_dir)
        registry.verify_runtime_dir_identity(registered)
    except Exception:
        _reject("runtime_registration_mismatch", "registered production runtime is unavailable")
    if registered is not admission_registration.runtime_registration:
        _reject("runtime_registration_mismatch", "production runtime does not match its pin")
    # The legacy ctp_production block remains parser-bound to its reserved
    # directory. The canonical ctp block can reuse the SimNow runtime
    # directory after the operator explicitly changes mode/preset and the
    # account/front/contract settings. This pure contract still requires an
    # exact injected production registration for that same directory.
    if os.path.normcase(str(registered.runtime_dir)) != os.path.normcase(
        str(config.strategy_dir.resolve(strict=False))
    ):
        _reject(
            "runtime_registration_mismatch", "production runtime does not match config directory"
        )

    effective_digest: Optional[str] = None
    profile_scoped = admission_registration.scope_binding_mode == "sealed_config" and bool(
        registered.profiles
    )
    if effective_runtime is not None:
        if type(effective_runtime) is not EffectiveRuntimeConfig:
            _reject(
                "effective_config_required", "a resolver-produced effective runtime is required"
            )
        try:
            require_effective_runtime_config_seal(effective_runtime, registry)
        except Exception:
            _reject(
                "effective_config_provenance_invalid", "effective runtime does not match its seal"
            )
        if (
            effective_runtime.config is not config
            or effective_runtime.registration is not registered
        ):
            _reject(
                "effective_config_mismatch", "effective runtime does not match the sealed config"
            )
        effective_digest = effective_runtime.effective_digest
    elif profile_scoped:
        _reject(
            "effective_config_required",
            "profile-scoped production requires its sealed effective runtime",
        )

    has_canonical_live_ctp = (
        config.ctp is not None and config.ctp_simnow is None and config.ctp_production is None
    )
    has_legacy_production_ctp = (
        config.ctp is None and config.ctp_simnow is None and config.ctp_production is not None
    )
    if admission_registration.scope_binding_mode == "sealed_config" and not has_canonical_live_ctp:
        _reject(
            "runtime_contract_mismatch",
            "sealed-config production scope requires the canonical live ctp block",
        )
    if has_legacy_production_ctp and admission_registration.scope_binding_mode != "pinned":
        _reject(
            "runtime_contract_mismatch",
            "legacy production config requires pinned scope registration",
        )

    profile = None
    if profile_scoped:
        assert effective_runtime is not None  # enforced above
        profile = effective_runtime.profile
        if (
            type(profile) is not RuntimeProfile
            or profile is not registered.profile_for("live", "managed_live_direct")
            or effective_runtime.config is not config
            or effective_runtime.registration is not registered
            or effective_runtime.policy.name != "managed_live_direct"
            or effective_runtime.policy.mode != "live"
            or effective_runtime.policy.environment != _PRODUCTION_ENVIRONMENT
            or effective_runtime.policy.required_capabilities != MANAGED_WRITE_CAPABILITIES
            or effective_runtime.order_route != "managed_execution"
            or effective_runtime.account_access != "direct_provider"
            or effective_runtime.required_capabilities != MANAGED_WRITE_CAPABILITIES
            or effective_runtime.allows_network is not True
            or effective_runtime.allows_external_writes is not True
            or effective_runtime.allows_production_writes is not True
            or effective_runtime.allows_hypothetical_fills is not False
            or effective_runtime.requires_approval is not True
            or effective_runtime.requires_live_confirmation is not True
            or config.mode != "live"
            or config.preset != "managed_live_direct"
            or config.secrets_ref != _SECRETS_REF
            or tuple(config.parameters) != ()
            or profile.allowed_parameter_keys != ()
            or profile.allowed_secrets_refs != (_SECRETS_REF,)
            or profile.available_capabilities != MANAGED_WRITE_CAPABILITIES
            or profile.approval_receipt_digest != admission_registration.approval_receipt_sha256
            or profile.offline_managed_execution is not False
            or profile.sandbox_write_policy != "deny"
            or not has_canonical_live_ctp
        ):
            _reject(
                "runtime_contract_mismatch",
                "selected profile is not the bounded CTP production execution contract",
            )
    elif (
        registered.strategy_id != config.strategy_id
        or registered.allowed_presets != ("managed_live_direct",)
        or registered.allowed_parameter_keys != ()
        or registered.allowed_secrets_refs != (_SECRETS_REF,)
        or registered.available_capabilities != MANAGED_WRITE_CAPABILITIES
        or registered.offline_managed_execution is not False
        or registered.sandbox_write_policy != "deny"
        or registered.approval_receipt_digest != admission_registration.approval_receipt_sha256
        or config.mode != "live"
        or config.preset != "managed_live_direct"
        or config.secrets_ref != _SECRETS_REF
        or tuple(config.parameters) != ()
        or not (has_canonical_live_ctp or has_legacy_production_ctp)
    ):
        _reject(
            "runtime_contract_mismatch",
            "sealed runtime is not the bounded CTP production execution contract",
        )

    if registered.strategy_id != config.strategy_id:
        _reject(
            "runtime_contract_mismatch",
            "sealed runtime strategy identity does not match the production config",
        )

    private = config.ctp if has_canonical_live_ctp else config.ctp_production
    if type(private) not in (CtpPrivateConfig, CtpProductionPrivateConfig):
        _reject("runtime_contract_mismatch", "sealed production CTP config is invalid")
    configured_account = production_account_binding_sha256(private.broker_id, private.user_id)
    if admission_registration.scope_binding_mode == "pinned":
        if (
            configured_account != admission_registration.account_binding_sha256
            or private.instrument_id != admission_registration.instrument_id
            or private.exchange_id != admission_registration.exchange_id
            or private.hedge_flag != admission_registration.hedge_flag
        ):
            _reject(
                "production_pin_mismatch",
                "configured CTP production account/contract scope does not match the pin",
            )

    configured_front_pairs = tuple(
        (pair["md_front"], pair["td_front"]) for pair in private.front_pairs
    )
    if not configured_front_pairs or len(configured_front_pairs) > 8:
        _reject("runtime_contract_mismatch", "sealed production front list is invalid")
    if (
        admission_registration.scope_binding_mode == "pinned"
        and len(configured_front_pairs) > 1
        and admission_registration.approved_front_pair_set_sha256 is None
    ):
        _reject(
            "production_front_set_approval_required",
            "multi-pair production config requires an approved candidate-set digest",
        )
    if (
        admission_registration.scope_binding_mode == "pinned"
        and admission_registration.approved_front_pair_set_sha256 is not None
    ):
        configured_set_digest = production_front_pair_set_sha256(configured_front_pairs)
        if configured_set_digest != admission_registration.approved_front_pair_set_sha256:
            _reject(
                "production_front_set_mismatch",
                "configured production front set does not match the approved set",
            )
    elif (
        admission_registration.scope_binding_mode == "pinned"
        and (
            admission_registration.md_front,
            admission_registration.td_front,
        )
        not in configured_front_pairs
    ):
        _reject("production_pin_mismatch", "approved production front is absent from config")

    if selected_front_pair is None and len(configured_front_pairs) == 1:
        selected_front_pair = configured_front_pairs[0]
    selected_front_index = None
    if selected_front_pair is not None:
        if (
            type(selected_front_pair) is not tuple
            or len(selected_front_pair) != 2
            or any(type(value) is not str for value in selected_front_pair)
            or selected_front_pair not in configured_front_pairs
        ):
            _reject(
                "production_front_selection_mismatch",
                "selected production fronts are not in sealed config",
            )
        if admission_registration.scope_binding_mode == "pinned" and (
            admission_registration.approved_front_pair_set_sha256 is None
            and selected_front_pair
            != (admission_registration.md_front, admission_registration.td_front)
        ):
            _reject(
                "production_pin_mismatch", "selected production fronts do not match exact approval"
            )
        selected_front_index = configured_front_pairs.index(selected_front_pair)
        md_front, td_front = selected_front_pair
        front_pair_sha256 = _front_pair_digest(md_front, td_front)
    else:
        md_front = None
        td_front = None
        front_pair_sha256 = "0" * 64

    configured_set_digest = production_front_pair_set_sha256(configured_front_pairs)
    scope_identity_sha256 = _scope_identity_digest(
        config_digest=config.config_digest,
        effective_digest=effective_digest,
        registration_digest=admission_registration.digest,
        account_binding_sha256=configured_account,
        instrument_id=private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        front_pair_set_sha256=configured_set_digest,
        front_pair_sha256=front_pair_sha256,
    )

    return CtpProductionExecutionConfigBinding(
        runtime_id=registered.runtime_id or "",
        strategy_id=config.strategy_id,
        config_digest=config.config_digest,
        effective_digest=effective_digest,
        runtime_registration_digest=registered.digest,
        registration_digest=admission_registration.digest,
        scope_identity_sha256=scope_identity_sha256,
        environment=_PRODUCTION_ENVIRONMENT,
        md_front=md_front,
        td_front=td_front,
        instrument_id=private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        account_binding_sha256=configured_account,
        approval_receipt_id=admission_registration.approval_receipt_id,
        approval_receipt_sha256=admission_registration.approval_receipt_sha256,
        artifact_id=admission_registration.artifact_id,
        artifact_sha256=admission_registration.artifact_sha256,
        allowed_sides=admission_registration.allowed_sides,
        allowed_offsets=admission_registration.allowed_offsets,
        quantity_step=admission_registration.quantity_step,
        max_order_quantity=admission_registration.max_order_quantity,
        max_gross_position=admission_registration.max_gross_position,
        min_price=admission_registration.min_price,
        max_price=admission_registration.max_price,
        price_tick=admission_registration.price_tick,
        max_order_notional=admission_registration.max_order_notional,
        front_pair_sha256=front_pair_sha256,
        front_pair_set_sha256=configured_set_digest,
        front_pairs=configured_front_pairs,
        selected_front_index=selected_front_index,
    )


__all__ = [
    "CtpProductionExecutionAdmissionError",
    "CtpProductionExecutionConfigBinding",
    "CtpProductionExecutionRegistration",
    "production_front_pair_set_sha256",
    "require_ctp_production_execution_config_binding",
]
