"""Pure CTP production configuration binding for future read-only work.

This module checks a sealed ``config.yaml`` against an exact code-owned
production registration. It has no credential resolver, SDK, provider, socket,
or execution dependency. A successful result records the exact configured
front pair and scope but authorizes no provider access of any kind.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from .config import (
    CtpPrivateConfig,
    RuntimeConfig,
    require_loaded_runtime_config_seal,
)
from .errors import RuntimeConfigError
from .registry import RegisteredRuntime, RuntimeRegistry


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_HEDGE_FLAGS = frozenset(("1", "2", "3"))
_SECRETS_REF = "config_yaml"
_PRODUCTION_ENVIRONMENT = "production"


class CtpProductionReadOnlyAdmissionError(ValueError):
    """Redacted fail-closed rejection for a production config binding."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpProductionReadOnlyAdmissionError(reason, message)


def _is_identifier(value: Any, pattern: re.Pattern[str]) -> bool:
    return (
        type(value) is str
        and value == value.strip()
        and pattern.fullmatch(value) is not None
    )


def _require_sha256(value: Any, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_registration", "invalid {0}".format(field_name))
    return value


def production_account_binding_sha256(broker_id: str, user_id: str) -> str:
    """Return a production-domain-separated digest for one configured account.

    This helper is for code-reviewed registration data. It accepts only the
    non-secret account selectors and deliberately has no SimNow counterpart.
    """

    if not _is_identifier(broker_id, _IDENTIFIER_RE) or not _is_identifier(
        user_id, _IDENTIFIER_RE
    ):
        _reject("invalid_account_binding", "invalid CTP production account selectors")
    payload = json.dumps([broker_id, user_id], ensure_ascii=True, separators=(",", ":"))
    material = b"backtrader-ctp-production-account-v1\0" + payload.encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _front_pair_sha256(md_front: str, td_front: str) -> str:
    payload = json.dumps([md_front, td_front], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(
        b"backtrader-ctp-production-front-pair-v1\0" + payload.encode("ascii")
    ).hexdigest()


def _front_pair_set_sha256(front_pairs: tuple[tuple[str, str], ...]) -> str:
    payload = json.dumps(front_pairs, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(
        b"backtrader-ctp-production-front-pair-set-v1\0" + payload.encode("ascii")
    ).hexdigest()


def _admission_digest(registration: "CtpProductionReadOnlyRegistration") -> str:
    payload = {
        "account_binding_sha256": registration.account_binding_sha256,
        "environment": registration.environment,
        "exchange_id": registration.exchange_id,
        "hedge_flag": registration.hedge_flag,
        "instrument_id": registration.instrument_id,
        "md_front": registration.md_front,
        "runtime_registration_digest": registration.runtime_registration.digest,
        "td_front": registration.td_front,
    }
    material = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        b"backtrader-ctp-production-readonly-admission-v2\0" + material.encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class CtpProductionReadOnlyRegistration:
    """Production account and query scope reviewed in code.

    This type is a data contract only. In particular it contains no password,
    AppID, AuthCode, receipt, environment selector, SDK profile, or write
    capability. ``md_front`` and ``td_front`` are an optional legacy exact-pair
    pin; when both are absent, only the sealed config supplies candidate fronts.
    The runtime registration must be the identical object present in the
    registry which sealed the loaded config.
    """

    runtime_registration: RegisteredRuntime
    environment: str
    account_binding_sha256: str = field(repr=False)
    # Optional legacy validation pin. This pair never supplies or selects an
    # endpoint; the sealed config's explicit front_pairs list remains source.
    md_front: str | None = field(repr=False)
    td_front: str | None = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str

    def __post_init__(self) -> None:
        if type(self.runtime_registration) is not RegisteredRuntime:
            _reject("invalid_registration", "invalid registered runtime binding")
        if type(self.environment) is not str or self.environment != _PRODUCTION_ENVIRONMENT:
            _reject(
                "environment_mismatch",
                "CTP production binding requires the exact production environment",
            )
        object.__setattr__(
            self,
            "account_binding_sha256",
            _require_sha256(self.account_binding_sha256, "account_binding_sha256"),
        )
        if (self.md_front is None) != (self.td_front is None):
            _reject("invalid_registration", "production legacy fronts must be both set or both absent")
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
        if not _is_identifier(self.instrument_id, _INSTRUMENT_RE):
            _reject("invalid_registration", "invalid production instrument_id")
        if not _is_identifier(self.exchange_id, _EXCHANGE_RE):
            _reject("invalid_registration", "invalid production exchange_id")
        if type(self.hedge_flag) is not str or self.hedge_flag not in _HEDGE_FLAGS:
            _reject("invalid_registration", "invalid production hedge_flag")


@dataclass(frozen=True)
class CtpProductionReadOnlyConfigBinding:
    """Digest-only evidence that one sealed production config matched its pin.

    Configured candidate pairs and any selected front values are retained for
    a future reviewed composition root, but omitted from repr and public
    serialization. All access and execution authority remains false.
    """

    runtime_id: str
    strategy_id: str
    config_digest: str
    registration_digest: str
    environment: str
    md_front: str | None = field(repr=False)
    td_front: str | None = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    account_binding_sha256: str = field(repr=False)
    front_pair_sha256: str
    front_pair_set_sha256: str
    front_pairs: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    contract_verified: bool = field(default=True, init=False)
    provider_read_authorized: bool = field(default=False, init=False)
    sdk_import_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)

    def __bool__(self) -> bool:
        raise TypeError(
            "CtpProductionReadOnlyConfigBinding is non-authorizing binding evidence; "
            "do not use it as provider admission"
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return redacted evidence without account selectors or front addresses."""

        return {
            "account_scope": "redacted",
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "config_digest": self.config_digest,
            "contract_verified": self.contract_verified,
            "credential_access_authorized": self.credential_access_authorized,
            "environment": self.environment,
            "exchange_id": self.exchange_id,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "front_pair_sha256": self.front_pair_sha256,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "network_access_authorized": self.network_access_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "provider": "ctp",
            "provider_read_authorized": self.provider_read_authorized,
            "registration_digest": self.registration_digest,
            "runtime_id": self.runtime_id,
            "sdk_import_authorized": self.sdk_import_authorized,
            "strategy_id": self.strategy_id,
        }


def _normalise_registration(value: Any) -> CtpProductionReadOnlyRegistration:
    if type(value) is not CtpProductionReadOnlyRegistration:
        _reject(
            "registration_required",
            "a code-owned CTP production read-only registration is required",
        )
    try:
        return CtpProductionReadOnlyRegistration(
            runtime_registration=value.runtime_registration,
            environment=value.environment,
            account_binding_sha256=value.account_binding_sha256,
            md_front=value.md_front,
            td_front=value.td_front,
            instrument_id=value.instrument_id,
            exchange_id=value.exchange_id,
            hedge_flag=value.hedge_flag,
        )
    except CtpProductionReadOnlyAdmissionError:
        raise
    except Exception:
        _reject("invalid_registration", "invalid CTP production registration")


def require_ctp_production_readonly_config_binding(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionReadOnlyRegistration,
    *,
    selected_front_pair: tuple[str, str] | None = None,
) -> CtpProductionReadOnlyConfigBinding:
    """Verify production account/scope and config fronts without I/O.

    ``config`` must be the loader-produced object sealed to ``registry``.
    Optional ``selected_front_pair`` must be one of the sealed config's
    candidates. Omitting it leaves multi-pair configs unresolved regardless
    of any legacy validation pin. This gate accepts no effective config or
    session factory, and the returned binding cannot authorize a read, SDK
    import, network call, credential resolution, or any execution action.
    """

    if type(config) is not RuntimeConfig:
        _reject("config_required", "a sealed production runtime config is required")
    if type(registry) is not RuntimeRegistry or registry.trusted is not True:
        _reject("registry_required", "a trusted runtime registry is required")
    registration = _normalise_registration(admission_registration)

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
    if registered is not registration.runtime_registration:
        _reject("runtime_registration_mismatch", "production runtime does not match its pin")
    # This candidate consumes only the canonical ``ctp`` block from the
    # registered config.yaml. Parser compatibility for the retired
    # ``ctp_production`` block does not make that second-file path an admitted
    # source. No default live registration is created here.
    if os.path.normcase(str(registered.runtime_dir)) != os.path.normcase(
        str(config.strategy_dir.resolve(strict=False))
    ):
        _reject("runtime_registration_mismatch", "production runtime does not match config directory")

    has_canonical_live_ctp = (
        config.ctp is not None
        and config.ctp_simnow is None
        and config.ctp_production is None
    )
    if not has_canonical_live_ctp:
        _reject(
            "canonical_ctp_config_required",
            "production read-only binding requires the canonical ctp block in the registered config",
        )
    if (
        registered.strategy_id != config.strategy_id
        or registered.allowed_presets != ("managed_live_direct",)
        or registered.allowed_parameter_keys != ()
        or registered.allowed_secrets_refs != (_SECRETS_REF,)
        or registered.available_capabilities != ()
        or registered.capability_modules != ()
        or registered.offline_managed_execution is not False
        or registered.sandbox_write_policy != "deny"
        or registered.approval_receipt_digest is not None
        or registered.runner_module is not None
        or config.mode != "live"
        or config.preset != "managed_live_direct"
        or config.secrets_ref != _SECRETS_REF
        or tuple(config.parameters) != ()
        or not has_canonical_live_ctp
    ):
        _reject(
            "runtime_contract_mismatch",
            "sealed runtime is not the injected CTP production read-only contract",
        )

    private = config.ctp
    if type(private) is not CtpPrivateConfig:
        _reject("runtime_contract_mismatch", "sealed production CTP config is invalid")
    configured_account = production_account_binding_sha256(
        private.broker_id,
        private.user_id,
    )
    if (
        configured_account != registration.account_binding_sha256
        or private.instrument_id != registration.instrument_id
        or private.exchange_id != registration.exchange_id
        or private.hedge_flag != registration.hedge_flag
    ):
        _reject(
            "production_pin_mismatch",
            "configured CTP production endpoints or account scope do not match the reviewed pin",
        )

    configured_front_pairs = tuple(
        (pair["md_front"], pair["td_front"]) for pair in private.front_pairs
    )
    if not configured_front_pairs or any(
        type(md_front) is not str or type(td_front) is not str
        for md_front, td_front in configured_front_pairs
    ):
        _reject("runtime_contract_mismatch", "sealed production front list is invalid")
    if len(configured_front_pairs) > 1 and registration.md_front is not None:
        _reject(
            "legacy_front_pin_incompatible_with_multi_pair_config",
            "multi-pair production config requires an unpinned config-driven registration",
        )
    if selected_front_pair is None and len(configured_front_pairs) == 1:
        selected_front_pair = configured_front_pairs[0]
    if selected_front_pair is not None:
        if (
            type(selected_front_pair) is not tuple
            or len(selected_front_pair) != 2
            or any(type(value) is not str for value in selected_front_pair)
        ):
            _reject("production_front_selection_mismatch", "selected fronts are not in sealed config")
        if selected_front_pair not in configured_front_pairs:
            if registration.md_front is not None and selected_front_pair == (
                registration.md_front,
                registration.td_front,
            ):
                _reject("production_pin_mismatch", "configured CTP production fronts do not match pin")
            _reject("production_front_selection_mismatch", "selected fronts are not in sealed config")
        if registration.md_front is not None and selected_front_pair != (
            registration.md_front,
            registration.td_front,
        ):
            _reject("production_pin_mismatch", "selected CTP production fronts do not match pin")
        md_front, td_front = selected_front_pair
        front_pair_sha256 = _front_pair_sha256(md_front, td_front)
    else:
        md_front = None
        td_front = None
        front_pair_sha256 = "0" * 64

    return CtpProductionReadOnlyConfigBinding(
        runtime_id=registered.runtime_id or "",
        strategy_id=config.strategy_id,
        config_digest=config.config_digest,
        registration_digest=_admission_digest(registration),
        environment=_PRODUCTION_ENVIRONMENT,
        md_front=md_front,
        td_front=td_front,
        instrument_id=private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        account_binding_sha256=configured_account,
        front_pair_sha256=front_pair_sha256,
        front_pair_set_sha256=_front_pair_set_sha256(configured_front_pairs),
        front_pairs=configured_front_pairs,
    )


__all__ = [
    "CtpProductionReadOnlyAdmissionError",
    "CtpProductionReadOnlyConfigBinding",
    "CtpProductionReadOnlyRegistration",
    "production_account_binding_sha256",
    "require_ctp_production_readonly_config_binding",
]
