"""Pathless, non-authorizing binding for validated private CTP configuration.

The public approval/receipt may carry the keyed tag returned here.  The raw
configuration and key never leave this module's calculation path.  Callers
must resolve a fresh tag for each approval-context refresh and compare it with
the tag already bound into the SDK's single approval/execution ledger; this
module deliberately keeps no journal or process-global cache.

This is only a binding source. It does not approve, connect, preflight, arm,
submit, cancel, or authorize any external write. A future writer must supply
its own reviewed trusted-time and expiry checks; these tags do not provide
time evidence or write authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

from .config import CtpSimNowPrivateConfig
from .ctp_sandbox_readonly_admission import (
    CtpSandboxReadOnlyAdmissionError,
    CtpSandboxReadOnlyRegistration,
    require_ctp_sandbox_readonly_runtime_contract,
)
from .errors import RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


_TAG_SCHEMA = "ctp.private-credential-binding.v2"
_TAG_DOMAIN = b"backtrader-runtime\x00ctp-private-credential-binding\x00v2\x00"
_REVIEWED_TAG_SCHEMA = "ctp.private-credential-binding.reviewed-route.v4"
_REVIEWED_TAG_DOMAIN = (
    b"backtrader-runtime\x00ctp-private-credential-binding\x00reviewed-route\x00v4\x00"
)
_REVIEWED_REFRESH_SCHEMA = "ctp.private-credential-binding.reviewed-sdk-scope.v4"
_REVIEWED_REFRESH_DOMAIN = (
    b"backtrader-runtime\x00ctp-private-credential-binding\x00reviewed-sdk-scope\x00v4\x00"
)
_CTP_SANDBOX_ENVIRONMENT = "simnow"
_CTP_CONFIGURED_FRONT_PAIR_MARKER = "config_front_pair"
_CTP_FRONT_PAIR_DOMAIN = b"backtrader-runtime\x00ctp-selected-front-pair\x00v1\x00"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HMAC_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_ACCOUNT_FINGERPRINT_RE = re.compile(r"^acct_[0-9a-f]{16}$")
_PRIVATE_FIELD_NAMES = (
    "md_front",
    "td_front",
    "front_pairs",
    "instrument_id",
    "exchange_id",
    "hedge_flag",
    "broker_id",
    "user_id",
    "password",
    "app_id",
    "auth_code",
)


class CtpCredentialBindingError(ValueError):
    """Stable failure that never includes configuration, key, or path values."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("CTP private credential binding is unavailable")


def _reject(reason: str) -> None:
    raise CtpCredentialBindingError(reason) from None


@dataclass(frozen=True)
class CtpCredentialBindingTag:
    """Small immutable SDK-context value; HMAC is omitted from repr."""

    key_id: str
    hmac_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.key_id) is not str or not _KEY_ID_RE.fullmatch(self.key_id):
            raise ValueError("key_id must be a code-owned key version identifier")
        if type(self.hmac_sha256) is not str or not _HMAC_RE.fullmatch(self.hmac_sha256):
            raise ValueError("hmac_sha256 must be a lower-case HMAC-SHA256 tag")

    def __repr__(self) -> str:
        return "CtpCredentialBindingTag(<redacted>)"

    def as_context_fields(self) -> Mapping[str, str]:
        """Return only the opaque HMAC tag and its non-secret key version id."""

        return {
            "credential_binding_key_id": self.key_id,
            "credential_binding_hmac_sha256": self.hmac_sha256,
        }


@dataclass(frozen=True)
class CtpCredentialBindingKeyMaterial:
    """One versioned protected HMAC key read; the bytes never leave runtime code."""

    key_id: str
    key_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.key_id) is not str or not _KEY_ID_RE.fullmatch(self.key_id):
            raise ValueError("key_id must be a code-owned key version identifier")
        if type(self.key_bytes) is not bytes or len(self.key_bytes) != 32:
            raise ValueError("key_bytes must be an exact 32-byte HMAC key")


@dataclass(frozen=True, init=False)
class CtpCredentialBindingKeySource:
    """Typed current-key reader used only inside the runtime adapter.

    ``read_current`` supplies key material, never route validity or approval.
    It is invoked afresh for every adapter refresh so a deployment can rotate
    the protected key version without restarting its SDK verifier.
    """

    _read_current: Callable[[], CtpCredentialBindingKeyMaterial] = field(repr=False, compare=False)

    def __init__(self, read_current: Callable[[], CtpCredentialBindingKeyMaterial]) -> None:
        if not callable(read_current):
            raise TypeError("read_current must load typed protected key material")
        object.__setattr__(self, "_read_current", read_current)

    def _current(self) -> CtpCredentialBindingKeyMaterial:
        try:
            material = self._read_current()
        except Exception:
            _reject("protected_key_unavailable")
        if type(material) is not CtpCredentialBindingKeyMaterial:
            _reject("protected_key_invalid")
        return material


@dataclass(frozen=True)
class CtpReviewedCredentialBindingRefreshResult:
    """Non-authorizing, pathless facts and HMAC for the SDK-owned verifier."""

    scope_sha256: str
    key_id: str
    hmac_sha256: str = field(repr=False)
    account_fingerprint: str = field(repr=False)
    account_fingerprint_sha256: str = field(repr=False)
    td_front: str = field(repr=False)
    md_front: str = field(repr=False)
    runtime_config_sha256: str = field(repr=False)
    registration_sha256: str = field(repr=False)
    backtrader_runtime_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in (
            "scope_sha256",
            "runtime_config_sha256",
            "registration_sha256",
            "account_fingerprint_sha256",
            "backtrader_runtime_sha256",
        ):
            value = getattr(self, name)
            if type(value) is not str or not _SHA256_RE.fullmatch(value):
                raise ValueError("{0} must be a lower-case SHA-256 digest".format(name))
        if type(self.key_id) is not str or not _KEY_ID_RE.fullmatch(self.key_id):
            raise ValueError("key_id must be a code-owned key version identifier")
        if type(self.hmac_sha256) is not str or not _HMAC_RE.fullmatch(self.hmac_sha256):
            raise ValueError("hmac_sha256 must be a lower-case HMAC-SHA256 tag")
        if (
            type(self.account_fingerprint) is not str
            or not _PUBLIC_ACCOUNT_FINGERPRINT_RE.fullmatch(self.account_fingerprint)
            or self.account_fingerprint
            != "acct_" + self.account_fingerprint_sha256[:16]
        ):
            raise ValueError("account_fingerprint must match account_fingerprint_sha256")
        if type(self.td_front) is not str or type(self.md_front) is not str:
            raise ValueError("configured fronts must be strings")

    def __repr__(self) -> str:
        return "CtpReviewedCredentialBindingRefreshResult(<redacted>)"


def _private_facts(private: CtpSimNowPrivateConfig) -> Tuple[object, ...]:
    if type(private) is not CtpSimNowPrivateConfig:
        _reject("private_config_unavailable")
    try:
        if tuple(item.name for item in fields(private)) != _PRIVATE_FIELD_NAMES:
            _reject("private_config_schema_changed")
        values = tuple(getattr(private, name) for name in _PRIVATE_FIELD_NAMES)
    except CtpCredentialBindingError:
        raise
    except Exception:
        _reject("private_config_unavailable")
    if len(values) != len(_PRIVATE_FIELD_NAMES):
        _reject("private_config_schema_changed")
    md_front, td_front, front_pairs = values[:3]
    if (md_front is None) != (td_front is None) or (
        md_front is not None and (type(md_front) is not str or type(td_front) is not str)
    ):
        _reject("private_config_unavailable")
    if type(front_pairs) is not tuple or not 1 <= len(front_pairs) <= 8:
        _reject("private_config_unavailable")
    normalized_pairs = []
    for pair in front_pairs:
        if not isinstance(pair, Mapping) or set(pair) != {"md_front", "td_front"}:
            _reject("private_config_unavailable")
        pair_md_front = pair.get("md_front")
        pair_td_front = pair.get("td_front")
        if type(pair_md_front) is not str or type(pair_td_front) is not str:
            _reject("private_config_unavailable")
        normalized_pairs.append((pair_md_front, pair_td_front))
    if len(set(normalized_pairs)) != len(normalized_pairs):
        _reject("private_config_unavailable")
    if md_front is not None and (
        len(front_pairs) != 1
        or front_pairs[0]["md_front"] != md_front
        or front_pairs[0]["td_front"] != td_front
    ):
        _reject("private_config_unavailable")
    if any(type(value) is not str for value in values[3:]):
        _reject("private_config_unavailable")
    return values


def _require_selected_front_pair(
    private: CtpSimNowPrivateConfig,
    admission: CtpSandboxReadOnlyRegistration,
) -> None:
    """Require the admission's exact ordered pair to occur in sealed config."""

    try:
        selected = (admission.md_front, admission.td_front)
        configured = tuple((pair["md_front"], pair["td_front"]) for pair in private.front_pairs)
    except Exception:
        _reject("admission_private_config_mismatch")
    if selected not in configured:
        _reject("admission_private_config_mismatch")
    if private.md_front is not None and (
        admission.md_front != private.md_front or admission.td_front != private.td_front
    ):
        _reject("admission_private_config_mismatch")


def _front_pair_digest(td_front: str, md_front: str) -> str:
    """Hash the exact ordered pair selected by sealed configuration.

    The marker says only that the configured pair is in use. It deliberately
    does not classify endpoints as a SimNow set or infer a venue environment.
    Keep TD and MD labels explicit so swapping two configured endpoints changes
    the binding even when their values are otherwise identical.
    """

    try:
        encoded = json.dumps(
            {"md_front": md_front, "td_front": td_front},
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except Exception:
        _reject("binding_material_invalid")
    return hashlib.sha256(_CTP_FRONT_PAIR_DOMAIN + encoded).hexdigest()


def _current_private_config(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
) -> Tuple[EffectiveRuntimeConfig, CtpSimNowPrivateConfig, CtpSandboxReadOnlyRegistration]:
    """Re-read through the verified registry loader; never trust a stale object."""

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    if type(admission_registration) is not CtpSandboxReadOnlyRegistration:
        _reject("readonly_admission_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        require_ctp_sandbox_readonly_runtime_contract(effective, registry, admission_registration)
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
        if current.registration is not effective.registration:
            _reject("runtime_identity_changed")
        admission = require_ctp_sandbox_readonly_runtime_contract(
            current, registry, admission_registration
        )
    except CtpCredentialBindingError:
        raise
    except (RuntimeConfigError, CtpSandboxReadOnlyAdmissionError):
        _reject("runtime_or_private_config_unavailable")
    except Exception:
        _reject("runtime_or_private_config_unavailable")

    original_private = effective.config.ctp_simnow
    current_private = current.config.ctp_simnow
    if type(original_private) is not CtpSimNowPrivateConfig:
        _reject("private_config_unavailable")
    if type(current_private) is not CtpSimNowPrivateConfig:
        _reject("private_config_unavailable")
    _require_selected_front_pair(original_private, admission_registration)
    _require_selected_front_pair(current_private, admission)
    if (
        effective.config.secrets_ref != "config_yaml"
        or current.config.secrets_ref != "config_yaml"
        or _private_facts(original_private) != _private_facts(current_private)
        or effective.config.config_digest != current.config.config_digest
        or effective.effective_digest != current.effective_digest
    ):
        _reject("stale_effective_config")

    try:
        account_fingerprint = hashlib.sha256(
            (current_private.broker_id + ":" + current_private.user_id).encode("utf-8")
        ).hexdigest()
    except Exception:
        _reject("admission_private_config_mismatch")
    if (
        admission.environment != _CTP_SANDBOX_ENVIRONMENT
        or admission.sdk_profile != _CTP_CONFIGURED_FRONT_PAIR_MARKER
        or admission.instrument_id != current_private.instrument_id
        or admission.exchange_id != current_private.exchange_id
        or admission.hedge_flag != current_private.hedge_flag
        or not hmac.compare_digest(
            admission.account_fingerprint_sha256,
            account_fingerprint,
        )
    ):
        _reject("admission_private_config_mismatch")

    return current, current_private, admission


def _load_key(key_provider: Callable[[], Tuple[str, bytes]]) -> Tuple[str, bytes]:
    if not callable(key_provider):
        _reject("protected_key_unavailable")
    try:
        material = key_provider()
    except Exception:
        _reject("protected_key_unavailable")
    if type(material) is not tuple or len(material) != 2:
        _reject("protected_key_invalid")
    key_id, key = material
    if type(key_id) is not str or not _KEY_ID_RE.fullmatch(key_id):
        _reject("protected_key_invalid")
    if type(key) is not bytes or len(key) != 32:
        _reject("protected_key_invalid")
    return key_id, key


def _canonical_payload(
    effective: EffectiveRuntimeConfig,
    private: CtpSimNowPrivateConfig,
    key_id: str,
    admission: CtpSandboxReadOnlyRegistration,
    *,
    schema: str = _TAG_SCHEMA,
    reviewed_binding: object = None,
    scope_sha256: Optional[str] = None,
    domain: Optional[bytes] = None,
) -> bytes:
    identity = {
        "runtime_id": effective.registration.runtime_id,
        "strategy_id": effective.registration.strategy_id,
        "registration_digest": effective.registration.digest,
        "effective_digest": effective.effective_digest,
        "config_digest": effective.config.config_digest,
    }
    private_values = dict(zip(_PRIVATE_FIELD_NAMES, _private_facts(private)))
    private_values["front_pairs"] = [
        {"md_front": pair["md_front"], "td_front": pair["td_front"]} for pair in private.front_pairs
    ]
    document = {
        "schema": schema,
        "key_id": key_id,
        "runtime_identity": identity,
        "admission": {
            "environment": admission.environment,
            "sdk_profile": admission.sdk_profile,
            "account_fingerprint_sha256": admission.account_fingerprint_sha256,
            "td_front": admission.td_front,
            "md_front": admission.md_front,
            "instrument_id": admission.instrument_id,
            "exchange_id": admission.exchange_id,
            "hedge_flag": admission.hedge_flag,
            "session_ttl_seconds": admission.session_ttl_seconds,
        },
        "provider_binding": {
            "provider": "ctp",
            "provider_environment": _CTP_SANDBOX_ENVIRONMENT,
            "selected_front_pair_sha256": _front_pair_digest(
                admission.td_front, admission.md_front
            ),
        },
        "ctp_simnow": private_values,
    }
    if reviewed_binding is not None:
        document["reviewed_route_binding"] = {
            "runtime_id": reviewed_binding.runtime_id,
            "session_ttl_seconds": reviewed_binding.session_ttl_seconds,
        }
    if scope_sha256 is not None:
        document["sdk_scope_sha256"] = scope_sha256
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except Exception:
        _reject("binding_material_invalid")
    selected_domain = domain
    if selected_domain is None:
        selected_domain = _REVIEWED_TAG_DOMAIN if reviewed_binding is not None else _TAG_DOMAIN
    return selected_domain + encoded


def refresh_ctp_credential_binding_tag(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    key_provider: Callable[[], Tuple[str, bytes]],
) -> CtpCredentialBindingTag:
    """Build a current tag after reloading and revalidating private config.

    ``key_provider`` is a no-argument, code-owned callback that obtains the
    exact 32-byte local protected key and its non-secret rotation id.  No key
    is retained here.  Call this for each SDK approval-context refresh; a
    changed config or key produces a different tag, which the SDK must compare
    to the tag in its existing approval/execution ledger.
    """

    current, private, admission = _current_private_config(
        effective, registry, admission_registration
    )
    key_id, key = _load_key(key_provider)
    payload = _canonical_payload(current, private, key_id, admission)
    tag = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return CtpCredentialBindingTag(key_id=key_id, hmac_sha256=tag)


def _same_admission(
    left: CtpSandboxReadOnlyRegistration,
    right: CtpSandboxReadOnlyRegistration,
) -> bool:
    """Compare every field carried by the SDK read-only admission value."""

    return (
        type(left) is CtpSandboxReadOnlyRegistration
        and type(right) is CtpSandboxReadOnlyRegistration
        and left.environment == _CTP_SANDBOX_ENVIRONMENT
        and right.environment == _CTP_SANDBOX_ENVIRONMENT
        and left.sdk_profile == _CTP_CONFIGURED_FRONT_PAIR_MARKER
        and right.sdk_profile == _CTP_CONFIGURED_FRONT_PAIR_MARKER
        and left.runtime_registration is right.runtime_registration
        and left.environment == right.environment
        and left.sdk_profile == right.sdk_profile
        and hmac.compare_digest(
            left.account_fingerprint_sha256,
            right.account_fingerprint_sha256,
        )
        and left.allowed_secrets_ref == right.allowed_secrets_ref
        and left.instrument_id == right.instrument_id
        and left.exchange_id == right.exchange_id
        and left.hedge_flag == right.hedge_flag
        and left.td_front == right.td_front
        and left.md_front == right.md_front
        and left.session_ttl_seconds == right.session_ttl_seconds
    )


def _current_reviewed_private_route(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
) -> Tuple[
    EffectiveRuntimeConfig,
    CtpSimNowPrivateConfig,
    CtpSandboxReadOnlyRegistration,
    object,
]:
    """Revalidate exact registered front policy and current sealed config."""

    current, private, normalized_admission = _current_private_config(
        effective, registry, admission_registration
    )
    try:
        binding = registry.require_ctp_simnow_readonly_binding(current.registration.runtime_id)
        from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
        from .ctp_front_pair_probe import CtpConfiguredFrontPair

        if type(binding) is not CtpSimNowConfigReadOnlyBinding:
            _reject("reviewed_route_required")
        # Reuse the already admitted pair for exact sealed-config membership
        # checks. Credential refresh must not re-probe or silently switch a
        # multi-pair runtime to a different configured candidate.
        selected_front_pair = CtpConfiguredFrontPair(
            md_front=normalized_admission.md_front,
            td_front=normalized_admission.td_front,
        )
        routed_admission, _scope = binding._route(
            current, registry, selected_front_pair=selected_front_pair
        )
    except CtpCredentialBindingError:
        raise
    except Exception:
        _reject("reviewed_route_unavailable")
    if not _same_admission(normalized_admission, routed_admission):
        _reject("reviewed_route_mismatch")
    return current, private, normalized_admission, binding


def _runtime_package_sha256() -> str:
    """Hash the loaded runtime package source/native manifest canonically."""

    root = Path(__file__).resolve().parent
    resolved_root = root.resolve()
    suffixes = {".py", ".so", ".dylib", ".pyd"}
    manifest = []
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in paths:
            relative_path = path.relative_to(root)
            if "__pycache__" in relative_path.parts:
                continue
            resolved_path = path.resolve()
            if path.is_symlink():
                try:
                    resolved_path.relative_to(resolved_root)
                except ValueError:
                    continue
            if not resolved_path.is_file() or path.suffix.lower() not in suffixes:
                continue
            relative = relative_path.as_posix()
            digest = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
            manifest.append({"path": relative, "sha256": digest})
        if not manifest:
            _reject("runtime_package_unavailable")
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except CtpCredentialBindingError:
        raise
    except Exception:
        _reject("runtime_package_unavailable")
    return hashlib.sha256(encoded).hexdigest()


def _sdk_scope_facts(scope: object) -> Tuple[str, str, str, str, str, str]:
    """Read only the SDK's nominal, already-loaded immutable scope object."""

    module = sys.modules.get("bt_api_py._ctp_credential_binding")
    scope_type = getattr(module, "CtpCredentialBindingScope", None)
    if scope_type is None or type(scope) is not scope_type:
        _reject("sdk_scope_required")
    try:
        scope_sha256 = scope.scope_sha256
        account_fingerprint = scope.account_fingerprint
        account_fingerprint_sha256 = scope.account_fingerprint_sha256
        td_front = scope.td_front
        md_front = scope.md_front
        runtime_package_sha256 = scope.backtrader_runtime_sha256
    except Exception:
        _reject("sdk_scope_invalid")
    if (
        type(scope_sha256) is not str
        or not _SHA256_RE.fullmatch(scope_sha256)
        or type(account_fingerprint) is not str
        or not _PUBLIC_ACCOUNT_FINGERPRINT_RE.fullmatch(account_fingerprint)
        or type(account_fingerprint_sha256) is not str
        or not _SHA256_RE.fullmatch(account_fingerprint_sha256)
        or account_fingerprint != "acct_" + account_fingerprint_sha256[:16]
        or type(td_front) is not str
        or type(md_front) is not str
        or type(runtime_package_sha256) is not str
        or not _SHA256_RE.fullmatch(runtime_package_sha256)
    ):
        _reject("sdk_scope_invalid")
    return (
        scope_sha256,
        account_fingerprint,
        account_fingerprint_sha256,
        td_front,
        md_front,
        runtime_package_sha256,
    )


_REFRESH_ADAPTER_FACTORY_TOKEN = object()


@dataclass(frozen=True, init=False)
class CtpReviewedCredentialBindingRefreshAdapter:
    """Deployment-owned bridge that refreshes one reviewed runtime binding.

    The SDK receives only a typed result.  The secret-key reader stays inside
    this adapter and supplies key material only; it cannot assert route
    validity, approve an execution, or grant any provider capability.
    """

    _effective: EffectiveRuntimeConfig = field(repr=False, compare=False)
    _registry: RuntimeRegistry = field(repr=False, compare=False)
    _admission: CtpSandboxReadOnlyRegistration = field(repr=False, compare=False)
    _key_source: CtpCredentialBindingKeySource = field(repr=False, compare=False)
    _runtime_package_sha256: str = field(repr=False, compare=False)

    def __init__(
        self,
        effective: EffectiveRuntimeConfig,
        registry: RuntimeRegistry,
        admission: CtpSandboxReadOnlyRegistration,
        key_source: CtpCredentialBindingKeySource,
        runtime_package_sha256: str,
        *,
        _factory_token: object = None,
    ) -> None:
        if _factory_token is not _REFRESH_ADAPTER_FACTORY_TOKEN:
            raise TypeError("use the reviewed deployment factory")
        object.__setattr__(self, "_effective", effective)
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_admission", admission)
        object.__setattr__(self, "_key_source", key_source)
        object.__setattr__(self, "_runtime_package_sha256", runtime_package_sha256)

    def refresh(self, scope: object) -> CtpReviewedCredentialBindingRefreshResult:
        """Revalidate runtime facts and return a fresh SDK-scoped HMAC result."""

        scope_facts = _sdk_scope_facts(scope)
        current, private, admission, binding = _current_reviewed_private_route(
            self._effective, self._registry, self._admission
        )
        (
            scope_sha256,
            scope_account,
            scope_account_sha256,
            scope_td_front,
            scope_md_front,
            scope_package_sha256,
        ) = scope_facts
        account_fingerprint_sha256 = hashlib.sha256(
            (private.broker_id + ":" + private.user_id).encode("utf-8")
        ).hexdigest()
        account_fingerprint = "acct_" + account_fingerprint_sha256[:16]
        runtime_package_sha256 = self._runtime_package_sha256
        if (
            scope_account != account_fingerprint
            or scope_account_sha256 != account_fingerprint_sha256
            or scope_td_front != admission.td_front
            or scope_md_front != admission.md_front
            or scope_package_sha256 != runtime_package_sha256
        ):
            _reject("sdk_scope_runtime_mismatch")

        material = self._key_source._current()
        payload = _canonical_payload(
            current,
            private,
            material.key_id,
            admission,
            schema=_REVIEWED_REFRESH_SCHEMA,
            reviewed_binding=binding,
            scope_sha256=scope_sha256,
            domain=_REVIEWED_REFRESH_DOMAIN,
        )
        tag = hmac.new(material.key_bytes, payload, hashlib.sha256).hexdigest()
        return CtpReviewedCredentialBindingRefreshResult(
            scope_sha256=scope_sha256,
            key_id=material.key_id,
            hmac_sha256=tag,
            account_fingerprint=account_fingerprint,
            account_fingerprint_sha256=account_fingerprint_sha256,
            td_front=admission.td_front,
            md_front=admission.md_front,
            runtime_config_sha256=current.config.config_digest,
            registration_sha256=current.registration.digest,
            backtrader_runtime_sha256=runtime_package_sha256,
        )


def create_reviewed_ctp_credential_binding_refresh_adapter(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    key_source: CtpCredentialBindingKeySource,
) -> CtpReviewedCredentialBindingRefreshAdapter:
    """Create the runtime-owned SDK bridge for one registered reviewed route.

    This factory resolves the exact route and captures one source-manifest
    digest before returning. ``refresh`` repeats the config, account, exact
    front-pair, registration, and scope checks before each fresh key read, then
    compares the SDK scope to that cached package identity. This is a binding
    source only.
    """

    if type(key_source) is not CtpCredentialBindingKeySource:
        _reject("typed_key_source_required")
    _current_reviewed_private_route(effective, registry, admission_registration)
    runtime_package_sha256 = _runtime_package_sha256()
    return CtpReviewedCredentialBindingRefreshAdapter(
        effective,
        registry,
        admission_registration,
        key_source,
        runtime_package_sha256,
        _factory_token=_REFRESH_ADAPTER_FACTORY_TOKEN,
    )


def refresh_reviewed_ctp_credential_binding_tag(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    key_provider: Callable[[], Tuple[str, bytes]],
) -> CtpCredentialBindingTag:
    """Build an HMAC tag after revalidating the registered config/front route.

    This remains a non-authorizing binding value.  It re-reads the protected
    config, resolves the exact trusted registry binding, reruns its exact front
    and query-scope checks, and compares the full newly routed admission before
    reading the HMAC key. No SDK or credential resolver is invoked.
    """

    current, private, admission, binding = _current_reviewed_private_route(
        effective, registry, admission_registration
    )
    key_id, key = _load_key(key_provider)
    payload = _canonical_payload(
        current,
        private,
        key_id,
        admission,
        schema=_REVIEWED_TAG_SCHEMA,
        reviewed_binding=binding,
    )
    tag = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return CtpCredentialBindingTag(key_id=key_id, hmac_sha256=tag)


def require_current_ctp_credential_binding_tag(
    expected_tag: CtpCredentialBindingTag,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    key_provider: Callable[[], Tuple[str, bytes]],
) -> None:
    """Fail closed unless a previously approved tag still matches now.

    The expected value must come from the already sealed SDK approval context
    or its single durable execution ledger; this module stores no second copy.
    """

    if type(expected_tag) is not CtpCredentialBindingTag:
        _reject("expected_binding_required")
    actual = refresh_ctp_credential_binding_tag(
        effective, registry, admission_registration, key_provider
    )
    if expected_tag.key_id != actual.key_id or not hmac.compare_digest(
        expected_tag.hmac_sha256, actual.hmac_sha256
    ):
        _reject("credential_binding_mismatch")


def require_current_reviewed_ctp_credential_binding_tag(
    expected_tag: CtpCredentialBindingTag,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    key_provider: Callable[[], Tuple[str, bytes]],
) -> None:
    """Fail closed unless an approved reviewed-route HMAC still matches."""

    if type(expected_tag) is not CtpCredentialBindingTag:
        _reject("expected_binding_required")
    actual = refresh_reviewed_ctp_credential_binding_tag(
        effective, registry, admission_registration, key_provider
    )
    if expected_tag.key_id != actual.key_id or not hmac.compare_digest(
        expected_tag.hmac_sha256, actual.hmac_sha256
    ):
        _reject("credential_binding_mismatch")


__all__ = [
    "CtpCredentialBindingError",
    "CtpCredentialBindingKeyMaterial",
    "CtpCredentialBindingKeySource",
    "CtpCredentialBindingTag",
    "CtpReviewedCredentialBindingRefreshAdapter",
    "CtpReviewedCredentialBindingRefreshResult",
    "create_reviewed_ctp_credential_binding_refresh_adapter",
    "refresh_ctp_credential_binding_tag",
    "refresh_reviewed_ctp_credential_binding_tag",
    "require_current_ctp_credential_binding_tag",
    "require_current_reviewed_ctp_credential_binding_tag",
]
