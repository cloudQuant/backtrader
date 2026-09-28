"""Opt-in verifier for one Store-staged Iteration 41 CTP action.

This module does not register a runtime, read operator configuration or keys,
construct an SDK client, or dispatch a provider request.  A deployment must
provide code-owned sealed-scope, permit, revocation, trusted-clock, and
account-wide writer-fence ports.  The default factory always rejects.

The scope resolver here is a typed port contract.  The separate
``ctp_managed_action_scope_resolver`` module supplies an opt-in sealed-config
candidate, but no deployment composition or active native-session host-pair
continuity check is provided here; this remains a local candidate contract.

The Store's durable single-use authority ledger remains the only local replay
ledger.  This verifier checks a signed permit before the Store claim and binds
its result to the exact persisted READY command.  Existing simulation review
permits and mode-specific approval DTOs are not accepted or converted to this
claim.  The verifier is a local admission component, not a substitute for a
service that owns the final revocation/fence check and the sole native CTP
handle.  Clock and epoch ports must remain non-rollback across process restarts;
the adapter's in-memory high-water checks cover only one verifier instance.
The ActionRef snapshot is only a typed consumer contract here: its source
digests are not authenticated, and floor/cutover monotonicity is remembered
only for this adapter instance.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass
from importlib.metadata import version
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple

from .ctp_managed_actionref_floor import (
    CtpManagedActionRefLedgerSnapshotV1,
    CtpManagedActionRefLedgerSource,
)


_PERMIT_SCHEMA = "ctp_managed_action_permit.v1"
_PERMIT_DOMAIN = "ctp.managed.action-claim.v1"
_AUTHORITY_TYPE = "ctp_dispatch_authority.v1"
_VERIFIER_ID = "ctp-managed-action-authority.v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
_MAX_CANONICAL_BYTES = 32 * 1024
_MAX_MAPPING_ITEMS = 128
_MAX_NESTING = 8
_MAX_TTL_NS = 5_000_000_000
_MAX_CLOCK_SKEW_NS = 250_000_000
_MAX_TRUST_SNAPSHOT_AGE_NS = 250_000_000
_MAX_NATIVE_INT = 2_147_483_647


class CtpManagedActionAuthorityError(RuntimeError):
    """Redacted fail-closed result from local CTP action verification."""


def _reject() -> None:
    raise CtpManagedActionAuthorityError("CTP managed action authority verification failed")


def _canonical_json(value: Any, *, depth: int = 0) -> bytes:
    """Encode a small bounded canonical JSON value without implicit coercions."""

    if depth > _MAX_NESTING:
        _reject()
    if isinstance(value, Mapping):
        if len(value) > _MAX_MAPPING_ITEMS:
            _reject()
        normalized = {}
        for key, child in value.items():
            if type(key) is not str or not key or len(key) > 128 or not key.isascii():
                _reject()
            normalized[key] = json.loads(_canonical_json(child, depth=depth + 1).decode("ascii"))
        value = normalized
    elif type(value) in (tuple, list):
        if len(value) > _MAX_MAPPING_ITEMS:
            _reject()
        value = [
            json.loads(_canonical_json(child, depth=depth + 1).decode("ascii")) for child in value
        ]
    elif value is None or type(value) in (str, int, float, bool):
        if type(value) is str and (len(value) > 4096 or not value.isascii()):
            _reject()
        if type(value) is float and (value != value or value in (float("inf"), float("-inf"))):
            _reject()
    else:
        _reject()
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject()
    if len(encoded) > _MAX_CANONICAL_BYTES:
        _reject()
    return encoded


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_id(value: Any) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        _reject()
    return value


def _require_digest(value: Any) -> str:
    if type(value) is not str or not _HEX_64.fullmatch(value):
        _reject()
    return value


def _load_v17_types() -> Optional[Tuple[type, ...]]:
    """Resolve exact Store types lazily; default imports never load the SDK."""

    if sys.version_info < (3, 11):
        return None
    try:
        if version("bt_api_execution") != "0.2.0":
            return None
        from bt_api_execution.contracts import ExecutionScope
        from bt_api_execution.store import (
            CtpCallbackSessionOwnerHandle,
            CtpCallbackSessionBindingV1,
            CtpDispatchAuthority,
            CtpDispatchCommand,
            SqliteExecutionStore,
            WriterLease,
        )
    except Exception:
        return None
    return (
        SqliteExecutionStore,
        ExecutionScope,
        CtpCallbackSessionOwnerHandle,
        CtpCallbackSessionBindingV1,
        WriterLease,
        CtpDispatchCommand,
        CtpDispatchAuthority,
    )


def _load_v17_native_binding_type() -> Optional[type]:
    """Resolve the Store-issued native binding without eager SDK imports."""

    if sys.version_info < (3, 11):
        return None
    try:
        if version("bt_api_execution") != "0.2.0":
            return None
        from bt_api_execution.store import CtpManagedNativeCallBindingV2
    except Exception:
        return None
    return CtpManagedNativeCallBindingV2


@dataclass(frozen=True)
class CtpManagedActionScopeV1:
    """Mode-neutral identity returned by a freshly validated scope resolver.

    A production resolver must rerun the existing sealed-runtime and
    mode-specific admission checks on every call.  This value alone is not
    authority and should not be built from caller request data.
    ``account_fingerprint_sha256`` is the exact digest suffix of the pinned
    execution scope's ``account_key``; it is not a free-standing account tag.
    """

    provider: str
    environment: str
    mode: str
    preset: str
    runtime_id: str
    strategy_id: str
    runtime_registration_digest: str
    mode_registration_digest: str
    config_digest: str
    effective_digest: str
    profile_digest: Optional[str]
    account_fingerprint_sha256: str
    front_pair_sha256: str
    front_pair_set_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.provider,
            self.environment,
            self.mode,
            self.preset,
            self.runtime_id,
            self.strategy_id,
        ):
            _require_id(value)
        if (self.environment, self.mode, self.preset) not in {
            ("simnow", "simulation", "sandbox"),
            ("production", "live", "managed_live_direct"),
        }:
            _reject()
        for value in (
            self.runtime_registration_digest,
            self.mode_registration_digest,
            self.config_digest,
            self.effective_digest,
            self.account_fingerprint_sha256,
            self.front_pair_sha256,
            self.front_pair_set_sha256,
        ):
            _require_digest(value)
        if self.profile_digest is not None:
            _require_digest(self.profile_digest)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "environment": self.environment,
            "mode": self.mode,
            "preset": self.preset,
            "runtime_id": self.runtime_id,
            "strategy_id": self.strategy_id,
            "runtime_registration_digest": self.runtime_registration_digest,
            "mode_registration_digest": self.mode_registration_digest,
            "config_digest": self.config_digest,
            "effective_digest": self.effective_digest,
            "profile_digest": self.profile_digest,
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "front_pair_sha256": self.front_pair_sha256,
            "front_pair_set_sha256": self.front_pair_set_sha256,
        }

    @property
    def digest(self) -> str:
        return _sha256({"domain": "ctp.managed.scope.v1", "scope": self.to_payload()})


class CtpManagedActionScopeResolver(Protocol):
    """Code-owned resolver that reruns sealed mode admission on every verify.

    Production implementations must call the existing sealed runtime and
    simulation/live plan validation functions and derive these digests from
    that result.  A bare mapping is rejected; tests use a typed fixture.
    """

    def resolve(self, command: Any, execution_scope: Any) -> CtpManagedActionScopeV1:
        """Return the current exact scope or fail closed."""


@dataclass(frozen=True)
class CtpManagedActionPermitV1:
    """Canonical signed claim created before Store staging.

    It intentionally binds only logical request identity. The Store allocates
    CANCEL ActionRef during staging; the verifier checks that exact native
    transformation after readback and binds the final command hash into the
    returned Store authority.
    """

    permit_id: str
    issuer: str
    key_id: str
    audience: str
    environment: str
    mode: str
    preset: str
    scope_sha256: str
    action_sha256: str
    issued_at_ns: int
    expires_at_ns: int
    revocation_epoch: int
    fence_id: str
    fence_epoch: int
    fence_owner_id: str
    nonce: str
    signature_hex: str
    schema: str = _PERMIT_SCHEMA

    def __post_init__(self) -> None:
        if type(self.schema) is not str or self.schema != _PERMIT_SCHEMA:
            _reject()
        for value in (
            self.permit_id,
            self.issuer,
            self.key_id,
            self.audience,
            self.environment,
            self.mode,
            self.preset,
            self.fence_id,
            self.fence_owner_id,
            self.nonce,
        ):
            _require_id(value)
        _require_digest(self.scope_sha256)
        _require_digest(self.action_sha256)
        for value in (
            self.issued_at_ns,
            self.expires_at_ns,
            self.revocation_epoch,
            self.fence_epoch,
        ):
            if type(value) is not int or value <= 0:
                _reject()
        if self.expires_at_ns <= self.issued_at_ns:
            _reject()
        if (
            type(self.signature_hex) is not str
            or len(self.signature_hex) != 128
            or not re.fullmatch(r"[0-9a-f]{128}", self.signature_hex, re.ASCII)
        ):
            _reject()

    def signed_claims(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "permit_id": self.permit_id,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "audience": self.audience,
            "environment": self.environment,
            "mode": self.mode,
            "preset": self.preset,
            "scope_sha256": self.scope_sha256,
            "action_sha256": self.action_sha256,
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "revocation_epoch": self.revocation_epoch,
            "fence_id": self.fence_id,
            "fence_epoch": self.fence_epoch,
            "fence_owner_id": self.fence_owner_id,
            "nonce": self.nonce,
        }

    def signed_payload(self) -> bytes:
        return _canonical_json({"domain": _PERMIT_DOMAIN, "claims": self.signed_claims()})

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "claims": self.signed_claims(),
                    "signature_hex": self.signature_hex,
                }
            )
        ).hexdigest()


@dataclass(frozen=True)
class CtpPinnedEd25519ActionKey:
    """One code/deployment-pinned verification key; no key loading occurs here."""

    issuer: str
    key_id: str
    audience: str
    public_key: bytes
    valid_from_ns: int
    valid_until_ns: int

    def __post_init__(self) -> None:
        for value in (self.issuer, self.key_id, self.audience):
            _require_id(value)
        if type(self.public_key) is not bytes or len(self.public_key) != 32:
            _reject()
        if (
            type(self.valid_from_ns) is not int
            or self.valid_from_ns <= 0
            or type(self.valid_until_ns) is not int
            or self.valid_until_ns <= self.valid_from_ns
        ):
            _reject()

    @property
    def digest(self) -> str:
        return _sha256(
            {
                "issuer": self.issuer,
                "key_id": self.key_id,
                "audience": self.audience,
                "public_key_sha256": hashlib.sha256(self.public_key).hexdigest(),
                "valid_from_ns": self.valid_from_ns,
                "valid_until_ns": self.valid_until_ns,
            }
        )


class PinnedEd25519CtpActionPermitVerifier:
    """Verify signatures against a structurally immutable Ed25519 pin mapping.

    This prevents accidental mutation through the verifier object; it is not a
    security boundary against hostile code in the same Python process.
    """

    __slots__ = ("_keys",)

    def __init__(self, keys: Tuple[CtpPinnedEd25519ActionKey, ...]) -> None:
        if type(keys) is not tuple or not keys:
            _reject()
        if any(type(key) is not CtpPinnedEd25519ActionKey for key in keys):
            _reject()
        if len({key.key_id for key in keys}) != len(keys):
            _reject()
        object.__setattr__(self, "_keys", MappingProxyType({key.key_id: key for key in keys}))

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_keys" and hasattr(self, "_keys"):
            raise AttributeError("the Ed25519 pin mapping is immutable")
        object.__setattr__(self, name, value)

    def verify(self, permit: CtpManagedActionPermitV1, *, now_ns: int) -> Tuple[str, int]:
        if type(permit) is not CtpManagedActionPermitV1 or type(now_ns) is not int or now_ns <= 0:
            _reject()
        key = self._keys.get(permit.key_id)
        if (
            key is None
            or permit.issuer != key.issuer
            or permit.audience != key.audience
            or permit.issued_at_ns < key.valid_from_ns
            or permit.issued_at_ns >= key.valid_until_ns
            or not key.valid_from_ns <= now_ns < key.valid_until_ns
        ):
            _reject()
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except Exception:
            _reject()
        try:
            Ed25519PublicKey.from_public_bytes(key.public_key).verify(
                bytes.fromhex(permit.signature_hex), permit.signed_payload()
            )
        except InvalidSignature:
            _reject()
        except Exception:
            _reject()
        return key.digest, key.valid_until_ns


class CtpManagedActionPermitSource(Protocol):
    def read_permit(self, permit_id: str) -> Optional[CtpManagedActionPermitV1]:
        """Resolve one exact permit by opaque one-use ID from an authenticated source."""


class CtpTrustedUtcClock(Protocol):
    def now_ns(self) -> int:
        """Return trusted UTC nanoseconds."""


@dataclass(frozen=True)
class CtpManagedActionRevocationSnapshot:
    permit_id: str
    key_id: str
    epoch: int
    revoked: bool
    key_active: bool
    observed_at_ns: int
    valid_until_ns: int
    source_digest_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.permit_id)
        _require_id(self.key_id)
        if (
            type(self.epoch) is not int
            or self.epoch <= 0
            or type(self.revoked) is not bool
            or type(self.key_active) is not bool
            or type(self.observed_at_ns) is not int
            or self.observed_at_ns <= 0
            or type(self.valid_until_ns) is not int
            or self.valid_until_ns <= self.observed_at_ns
        ):
            _reject()
        _require_digest(self.source_digest_sha256)


class CtpManagedActionRevocationSource(Protocol):
    def read_revocation(
        self, permit: CtpManagedActionPermitV1
    ) -> Optional[CtpManagedActionRevocationSnapshot]:
        """Return exact current revocation and epoch; None/errors mean unknown."""


@dataclass(frozen=True)
class CtpManagedActionWriterFenceSnapshot:
    fence_id: str
    owner_id: str
    account_fingerprint_sha256: str
    environment: str
    mode: str
    epoch: int
    observed_at_ns: int
    expires_at_ns: int
    source_digest_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.fence_id)
        _require_id(self.owner_id)
        _require_digest(self.account_fingerprint_sha256)
        _require_id(self.environment)
        _require_id(self.mode)
        for value in (self.epoch, self.observed_at_ns, self.expires_at_ns):
            if type(value) is not int or value <= 0:
                _reject()
        _require_digest(self.source_digest_sha256)


class CtpManagedActionWriterFenceSource(Protocol):
    def read_active_fence(
        self, scope: CtpManagedActionScopeV1
    ) -> Optional[CtpManagedActionWriterFenceSnapshot]:
        """Read the current external account-wide fence; missing/error denies."""


class CtpManagedActionAuthorityAdapter:
    """Freshly verify and bind one staged I9 CTP command to a signed permit.

    Every dependency is a constructor-pinned trust port.  In production those
    ports must be created by a code-owned deployment composition, not supplied
    by a strategy or order request.  The returned authority only feeds the
    Store's existing single-use ledger; this method cannot atomically hold an
    external fence through a later native ``Req*`` call.
    """

    def __init__(
        self,
        *,
        store: Any,
        scope: Any,
        owner_handle: Any,
        writer_lease: Any,
        scope_resolver: CtpManagedActionScopeResolver,
        permit_source: CtpManagedActionPermitSource,
        signature_verifier: PinnedEd25519CtpActionPermitVerifier,
        revocation_source: CtpManagedActionRevocationSource,
        fence_source: CtpManagedActionWriterFenceSource,
        trusted_clock: CtpTrustedUtcClock,
        action_ref_ledger_source: Optional[CtpManagedActionRefLedgerSource] = None,
    ) -> None:
        types = _load_v17_types()
        if types is None:
            _reject()
        store_type, scope_type, owner_type, session_type, lease_type, _, _ = types
        if (
            type(store) is not store_type
            or type(scope) is not scope_type
            or type(owner_handle) is not owner_type
            or type(writer_lease) is not lease_type
        ):
            _reject()
        if (
            store._issued_ctp_callback_session_owners.get(owner_handle.owner_intent_id)
            is not owner_handle
        ):
            _reject()
        if (
            owner_handle.account_key != scope.account_key
            or owner_handle.scope_key != scope.key
            or writer_lease.scope_key != scope.account_key
            or type(writer_lease.fencing_token) is not int
            or writer_lease.fencing_token <= 0
            or type(writer_lease.expires_at_ns) is not int
            or writer_lease.expires_at_ns <= 0
        ):
            _reject()
        for dependency, method in (
            (scope_resolver, "resolve"),
            (permit_source, "read_permit"),
            (revocation_source, "read_revocation"),
            (fence_source, "read_active_fence"),
            (trusted_clock, "now_ns"),
        ):
            if not callable(getattr(dependency, method, None)):
                _reject()
        if action_ref_ledger_source is not None and not callable(
            getattr(action_ref_ledger_source, "read_action_ref_ledger", None)
        ):
            _reject()
        if type(signature_verifier) is not PinnedEd25519CtpActionPermitVerifier:
            _reject()
        self._store = store
        self._scope = scope
        self._owner_handle = owner_handle
        self._writer_lease = writer_lease
        self._scope_resolver = scope_resolver
        self._permit_source = permit_source
        self._signature_verifier = signature_verifier
        self._revocation_source = revocation_source
        self._fence_source = fence_source
        self._trusted_clock = trusted_clock
        self._action_ref_ledger_source = action_ref_ledger_source
        self._clock_lock = threading.Lock()
        self._action_ref_lock = threading.Lock()
        self._last_trusted_now_ns: Optional[int] = None
        self._last_revocation_epoch: dict[Tuple[str, str], int] = {}
        self._last_fence_epoch: dict[Tuple[str, str], int] = {}
        self._last_action_ref_ledger_snapshot: dict[str, CtpManagedActionRefLedgerSnapshotV1] = {}

    def verify_action(self, command: Any, *, now_ns: int) -> Any:
        """Implement the execution Store's READY-claim verifier protocol."""

        return self._verify_action_state(
            command,
            now_ns=now_ns,
            expected_status="READY",
            issue_store_authority=True,
        )

    def verify_claimed_action(
        self,
        command: Any,
        binding: Any,
        *,
        now_ns: int,
    ) -> None:
        """Revalidate a claimed request at the final local native-call gate.

        This reuses the exact permit, sealed-scope, Ed25519, revocation, fence,
        trusted-clock, session, and writer-lease checks used at claim time.
        It intentionally returns no ``CtpDispatchAuthority`` and never claims
        or consumes an approval use a second time.  The SDK has already
        consumed the Store-issued V2 binding once before invoking this final
        check; this method only re-reads the claimed command and compares that
        binding to the immutable command snapshot.

        This remains a local pre-Req check. It cannot hold an external fence
        atomically through the provider call or replace a service-owned final
        authorization boundary.
        """

        types = _load_v17_types()
        binding_type = _load_v17_native_binding_type()
        if types is None or binding_type is None:
            _reject()
        store_type, scope_type, owner_type, _, lease_type, command_type, _ = types
        if (
            type(self._store) is not store_type
            or type(self._scope) is not scope_type
            or type(self._owner_handle) is not owner_type
            or type(self._writer_lease) is not lease_type
            or type(command) is not command_type
            or type(binding) is not binding_type
            or type(now_ns) is not int
            or now_ns <= 0
            or command.status != "CLAIMED"
            or binding.command_id != command.command_id
            or binding.owner_intent_id != self._owner_handle.owner_intent_id
            or binding.account_key != self._scope.account_key
            or binding.scope_key != self._scope.key
            or binding.trading_day != self._scope.trading_day
            or binding.writer_owner_id != self._writer_lease.owner_id
            or type(binding.writer_fencing_token) is not int
            or binding.writer_fencing_token != self._writer_lease.fencing_token
            or type(binding.native_request_id) is not int
            or binding.native_request_id <= 0
            or (
                binding.native_action_ref is not None
                and (type(binding.native_action_ref) is not int or binding.native_action_ref <= 0)
            )
            or type(binding.expires_at_ns) is not int
            or binding.expires_at_ns <= now_ns
        ):
            _reject()
        try:
            stored = self._store.read_ctp_dispatch_command(self._scope, command.command_id)
            if (
                type(stored) is not command_type
                or stored.status != "CLAIMED"
                or stored != command
                or stored.authority_binding_sha256 != command.authority_binding_sha256
                or stored.approval_use_id != command.approval_use_id
                or stored.approval_digest != command.approval_digest
            ):
                _reject()
            self._require_binding_matches_claimed_command(stored, binding)
            self._store.assert_writer_lease(self._scope, self._writer_lease)
        except CtpManagedActionAuthorityError:
            raise
        except Exception:
            _reject()

        # The Store claim transaction already consumed this one-use approval.
        # Final checking re-verifies it but does not return/submit another
        # Store authority object, preventing a second ledger consumption.
        self._verify_action_state(
            stored,
            now_ns=now_ns,
            expected_status="CLAIMED",
            issue_store_authority=False,
            required_expiry_ns=binding.expires_at_ns,
        )

    @staticmethod
    def _require_binding_matches_claimed_command(command: Any, binding: Any) -> None:
        correlation = command.correlation_key
        if (
            correlation is None
            or type(binding.dispatch_front_id) is not int
            or binding.dispatch_front_id <= 0
            or type(binding.dispatch_session_id) is not int
            or binding.dispatch_session_id <= 0
            or type(binding.writer_fencing_token) is not int
            or binding.writer_fencing_token <= 0
            or type(binding.expires_at_ns) is not int
            or binding.expires_at_ns <= 0
        ):
            _reject()
        logical_payload = _canonical_json(dict(command.request_payload)).decode("ascii")
        native_payload = _canonical_json(dict(command.native_request_payload)).decode("ascii")
        expected = (
            (binding.command_id, command.command_id),
            (binding.operation, command.operation),
            (binding.account_key, command.account_key),
            (binding.scope_key, command.scope_key),
            (binding.trading_day, command.trading_day),
            (binding.request_payload_json, logical_payload),
            (binding.request_payload_sha256, command.request_payload_sha256),
            (binding.native_request_payload_json, native_payload),
            (binding.native_request_payload_sha256, command.native_request_payload_sha256),
            (binding.reservation_managed_intent_id, command.reservation_managed_intent_id),
            (binding.managed_action_id, correlation.managed_action_id),
            (binding.runtime_order_id, correlation.runtime_order_id),
            (binding.order_ref, correlation.order_ref),
            (binding.native_request_id, correlation.native_request_id),
            (binding.native_action_ref, correlation.native_action_ref),
            (binding.session_binding_sha256, command.session_binding_sha256),
            (binding.session_generation_id, correlation.session_generation_id),
            (binding.dispatch_front_id, correlation.dispatch_front_id),
            (binding.dispatch_session_id, correlation.dispatch_session_id),
            (binding.cancel_target_order_ref, command.cancel_target_order_ref),
            (binding.cancel_target_exchange_id, command.cancel_target_exchange_id),
            (binding.cancel_target_order_sys_id, command.cancel_target_order_sys_id),
            (binding.cancel_target_front_id, command.cancel_target_front_id),
            (binding.cancel_target_session_id, command.cancel_target_session_id),
        )
        if any(actual != required for actual, required in expected):
            _reject()

    def _verify_action_state(
        self,
        command: Any,
        *,
        now_ns: int,
        expected_status: str,
        issue_store_authority: bool,
        required_expiry_ns: Optional[int] = None,
    ) -> Any:
        """Shared trust core for initial claim and final claimed recheck."""

        types = _load_v17_types()
        if types is None:
            _reject()
        (
            store_type,
            scope_type,
            owner_type,
            session_type,
            lease_type,
            command_type,
            authority_type,
        ) = types
        if (
            type(self._store) is not store_type
            or type(self._scope) is not scope_type
            or type(self._owner_handle) is not owner_type
            or type(self._writer_lease) is not lease_type
            or type(command) is not command_type
            or type(now_ns) is not int
            or now_ns <= 0
            or (
                required_expiry_ns is not None
                and (type(required_expiry_ns) is not int or required_expiry_ns <= now_ns)
            )
            or type(self._writer_lease.fencing_token) is not int
            or self._writer_lease.fencing_token <= 0
            or type(self._writer_lease.expires_at_ns) is not int
            or self._writer_lease.expires_at_ns <= now_ns
        ):
            _reject()
        try:
            trusted_now_before = self._check_trusted_clock(now_ns)
            stored = self._store.read_ctp_dispatch_command(self._scope, command.command_id)
            if (
                type(stored) is not command_type
                or stored.status != expected_status
                or command.status != expected_status
                or stored.authority_binding_sha256 != command.authority_binding_sha256
            ):
                _reject()
            # All later derivation consumes the Store's canonical row object,
            # not the callback argument, even after its complete hash matches.
            command = stored
            if (
                command.account_key != self._scope.account_key
                or command.scope_key != self._scope.key
                or command.trading_day != self._scope.trading_day
            ):
                _reject()
            self._store.assert_writer_lease(self._scope, self._writer_lease)
            session_binding, session_broker_id, session_user_id = (
                self._store.read_ctp_callback_session_context_facts(self._owner_handle)
            )
            if type(session_binding) is not session_type:
                _reject()
            self._check_session_binding(command, session_binding)
            validate_action_context = getattr(self._scope_resolver, "validate_action_context", None)
            if not callable(validate_action_context):
                _reject()
            scope = validate_action_context(
                command,
                self._scope,
                session_binding=session_binding,
                session_broker_id=session_broker_id,
                session_user_id=session_user_id,
            )
            if type(scope) is not CtpManagedActionScopeV1:
                _reject()
            account_key = self._scope.account_key
            if (
                type(account_key) is not str
                or not account_key.startswith("account:")
                or _HEX_64.fullmatch(account_key[len("account:") :]) is None
            ):
                _reject()
            if (
                scope.provider != self._scope.provider
                or scope.environment != self._scope.environment
                or scope.strategy_id != self._scope.strategy_id
                or scope.account_fingerprint_sha256 != account_key[len("account:") :]
            ):
                _reject()
            action_digest = self._action_digest(command, scope)
            action_ref_snapshot = self._read_action_ref_snapshot(
                command,
                account_key=account_key,
                now_ns=trusted_now_before,
                expected_status=expected_status,
            )
            permit = self._permit_source.read_permit(command.approval_use_id)
            if type(permit) is not CtpManagedActionPermitV1:
                _reject()
            if (
                permit.permit_id != command.approval_use_id
                or permit.digest != command.approval_digest
                or permit.scope_sha256 != scope.digest
                or permit.action_sha256 != action_digest
                or permit.environment != scope.environment
                or permit.mode != scope.mode
                or permit.preset != scope.preset
                or permit.expires_at_ns - permit.issued_at_ns > _MAX_TTL_NS
                or permit.issued_at_ns > trusted_now_before + _MAX_CLOCK_SKEW_NS
                or permit.expires_at_ns <= trusted_now_before
            ):
                _reject()
            fence = self._fence_source.read_active_fence(scope)
            if type(fence) is not CtpManagedActionWriterFenceSnapshot:
                _reject()
            if (
                fence.account_fingerprint_sha256 != scope.account_fingerprint_sha256
                or fence.environment != scope.environment
                or fence.mode != scope.mode
                or fence.fence_id != permit.fence_id
                or fence.epoch != permit.fence_epoch
                or fence.owner_id != permit.fence_owner_id
            ):
                _reject()
            if (
                fence.observed_at_ns > trusted_now_before + _MAX_CLOCK_SKEW_NS
                or trusted_now_before - fence.observed_at_ns > _MAX_TRUST_SNAPSHOT_AGE_NS
                or fence.expires_at_ns <= trusted_now_before
            ):
                _reject()
            key_digest, key_valid_until_ns = self._signature_verifier.verify(
                permit, now_ns=trusted_now_before
            )
            revocation = self._revocation_source.read_revocation(permit)
            if (
                type(revocation) is not CtpManagedActionRevocationSnapshot
                or revocation.permit_id != permit.permit_id
                or revocation.key_id != permit.key_id
                or revocation.epoch != permit.revocation_epoch
                or revocation.revoked is not False
                or revocation.key_active is not True
                or revocation.observed_at_ns > trusted_now_before + _MAX_CLOCK_SKEW_NS
                or trusted_now_before - revocation.observed_at_ns > _MAX_TRUST_SNAPSHOT_AGE_NS
                or revocation.valid_until_ns <= trusted_now_before
            ):
                _reject()
            with self._clock_lock:
                revocation_key = (permit.issuer, permit.key_id)
                prior_revocation_epoch = self._last_revocation_epoch.get(revocation_key)
                prior_fence_epoch = self._last_fence_epoch.get((scope.digest, fence.fence_id))
                if (
                    prior_revocation_epoch is not None and revocation.epoch < prior_revocation_epoch
                ) or (prior_fence_epoch is not None and fence.epoch < prior_fence_epoch):
                    _reject()
                self._last_revocation_epoch[revocation_key] = revocation.epoch
                self._last_fence_epoch[(scope.digest, fence.fence_id)] = fence.epoch
            trusted_now_after = self._check_trusted_clock(now_ns)
            if (
                permit.issued_at_ns > trusted_now_after + _MAX_CLOCK_SKEW_NS
                or permit.expires_at_ns <= trusted_now_after
                or key_valid_until_ns <= trusted_now_after
                or revocation.observed_at_ns > trusted_now_after + _MAX_CLOCK_SKEW_NS
                or trusted_now_after - revocation.observed_at_ns > _MAX_TRUST_SNAPSHOT_AGE_NS
                or revocation.valid_until_ns <= trusted_now_after
                or fence.observed_at_ns > trusted_now_after + _MAX_CLOCK_SKEW_NS
                or trusted_now_after - fence.observed_at_ns > _MAX_TRUST_SNAPSHOT_AGE_NS
                or fence.expires_at_ns <= trusted_now_after
                or self._writer_lease.expires_at_ns <= trusted_now_after
                or (required_expiry_ns is not None and required_expiry_ns <= trusted_now_after)
            ):
                _reject()
            action_ref_snapshot = self._read_action_ref_snapshot(
                command,
                account_key=account_key,
                now_ns=trusted_now_after,
                expected_status=expected_status,
            )
            self._store.assert_writer_lease(self._scope, self._writer_lease)
            revocation_fresh_until_ns = revocation.observed_at_ns + _MAX_TRUST_SNAPSHOT_AGE_NS
            fence_fresh_until_ns = fence.observed_at_ns + _MAX_TRUST_SNAPSHOT_AGE_NS
            expires_at_ns = min(
                permit.expires_at_ns,
                revocation.valid_until_ns,
                revocation_fresh_until_ns,
                fence.expires_at_ns,
                fence_fresh_until_ns,
                (
                    action_ref_snapshot.fresh_until_ns
                    if action_ref_snapshot is not None
                    else permit.expires_at_ns
                ),
                key_valid_until_ns,
                self._writer_lease.expires_at_ns,
            )
            if expires_at_ns <= now_ns:
                _reject()
            source_digest = _sha256(
                {
                    "domain": "ctp.managed.action-authority-source.v1",
                    "permit_digest": permit.digest,
                    "permit_id": permit.permit_id,
                    "issuer": permit.issuer,
                    "key_id": permit.key_id,
                    "action_digest": action_digest,
                    "command_binding_sha256": command.authority_binding_sha256,
                    "key_pin_digest": key_digest,
                    "key_valid_until_ns": key_valid_until_ns,
                    "revocation_epoch": revocation.epoch,
                    "permit_revoked": revocation.revoked,
                    "key_active": revocation.key_active,
                    "revocation_observed_at_ns": revocation.observed_at_ns,
                    "revocation_fresh_until_ns": revocation_fresh_until_ns,
                    "revocation_valid_until_ns": revocation.valid_until_ns,
                    "revocation_digest": revocation.source_digest_sha256,
                    "fence_id": fence.fence_id,
                    "fence_owner_id": fence.owner_id,
                    "fence_account_fingerprint_sha256": fence.account_fingerprint_sha256,
                    "fence_environment": fence.environment,
                    "fence_mode": fence.mode,
                    "fence_epoch": fence.epoch,
                    "fence_observed_at_ns": fence.observed_at_ns,
                    "fence_fresh_until_ns": fence_fresh_until_ns,
                    "fence_expires_at_ns": fence.expires_at_ns,
                    "fence_digest": fence.source_digest_sha256,
                    "action_ref_ledger_digest": (
                        action_ref_snapshot.digest if action_ref_snapshot is not None else None
                    ),
                    "writer_lease_expires_at_ns": self._writer_lease.expires_at_ns,
                    "scope_digest": scope.digest,
                }
            )
            if not issue_store_authority:
                return None
            return authority_type(
                authority_type=_AUTHORITY_TYPE,
                command_binding_sha256=command.authority_binding_sha256,
                approval_use_id=command.approval_use_id,
                approval_digest=command.approval_digest,
                source_digest_sha256=source_digest,
                verifier_id=_VERIFIER_ID,
                verified_at_ns=now_ns,
                expires_at_ns=expires_at_ns,
            )
        except CtpManagedActionAuthorityError:
            raise
        except Exception:
            _reject()

    def _read_action_ref_snapshot(
        self,
        command: Any,
        *,
        account_key: str,
        now_ns: int,
        expected_status: str,
    ) -> Optional[CtpManagedActionRefLedgerSnapshotV1]:
        """Require internally consistent account-wide floor/mapping data for CANCEL."""

        if command.operation != "CANCEL":
            return None
        source = self._action_ref_ledger_source
        if source is None:
            _reject()
        try:
            snapshot = source.read_action_ref_ledger(account_key)
            if type(snapshot) is not CtpManagedActionRefLedgerSnapshotV1:
                _reject()
            correlation = command.correlation_key
            with self._action_ref_lock:
                previous = self._last_action_ref_ledger_snapshot.get(account_key)
                self._require_action_ref_snapshot_monotonic(previous, snapshot)
                snapshot.require_current_cancel(
                    now_ns=now_ns,
                    account_key=account_key,
                    command_id=command.command_id,
                    scope_key=command.scope_key,
                    managed_action_id=correlation.managed_action_id,
                    native_action_ref=correlation.native_action_ref,
                    expected_status=expected_status,
                )
                self._last_action_ref_ledger_snapshot[account_key] = snapshot
            return snapshot
        except CtpManagedActionAuthorityError:
            raise
        except Exception:
            _reject()

    @staticmethod
    def _require_action_ref_snapshot_monotonic(
        previous: Optional[CtpManagedActionRefLedgerSnapshotV1],
        current: CtpManagedActionRefLedgerSnapshotV1,
    ) -> None:
        """Reject rollback or an unauthenticated cutover change in this process."""

        if previous is None:
            return
        if current.ledger_epoch < previous.ledger_epoch:
            _reject()
        if (
            current.cutover_id != previous.cutover_id
            or current.cutover_floor != previous.cutover_floor
        ):
            # No cutover-transition proof contract exists, so this adapter
            # cannot accept a new identity or floor after observing one.
            _reject()
        if (
            current.observed_native_high_water < previous.observed_native_high_water
            or current.counter_high_water < previous.counter_high_water
        ):
            _reject()
        if current.ledger_epoch == previous.ledger_epoch:
            if current.digest != previous.digest:
                _reject()
            return

        previous_by_ref = {row.native_action_ref: row for row in previous.allocations}
        current_by_ref = {row.native_action_ref: row for row in current.allocations}
        status_rank = {"READY": 0, "CLAIMED": 1, "COMPLETED": 2}
        for action_ref, old_row in previous_by_ref.items():
            new_row = current_by_ref.get(action_ref)
            if new_row is None or (
                new_row.account_key,
                new_row.command_id,
                new_row.scope_key,
                new_row.managed_action_id,
            ) != (
                old_row.account_key,
                old_row.command_id,
                old_row.scope_key,
                old_row.managed_action_id,
            ):
                _reject()
            if status_rank.get(new_row.status, -1) < status_rank.get(old_row.status, -1):
                _reject()
        if any(
            action_ref not in previous_by_ref and action_ref <= previous.counter_high_water
            for action_ref in current_by_ref
        ):
            _reject()

    def _check_trusted_clock(self, store_now_ns: int) -> int:
        before = self._trusted_clock.now_ns()
        if type(before) is not int or before <= 0:
            _reject()
        with self._clock_lock:
            if self._last_trusted_now_ns is not None and before < self._last_trusted_now_ns:
                _reject()
            self._last_trusted_now_ns = before
        if abs(before - store_now_ns) > _MAX_CLOCK_SKEW_NS:
            _reject()
        after = self._trusted_clock.now_ns()
        if (
            type(after) is not int
            or after < before
            or abs(after - store_now_ns) > _MAX_CLOCK_SKEW_NS
        ):
            _reject()
        with self._clock_lock:
            if self._last_trusted_now_ns is not None and after < self._last_trusted_now_ns:
                _reject()
            self._last_trusted_now_ns = after
        return after

    @staticmethod
    def _check_session_binding(command: Any, active: Any) -> None:
        correlation = command.correlation_key
        if (
            correlation is None
            or correlation.version != 2
            or command.native_request_payload is None
        ):
            _reject()
        binding_payload = {
            "binding_type": "ctp_callback_session_binding.v1",
            "owner_intent_id": active.owner_intent_id,
            "account_key": active.account_key,
            "scope_key": active.scope_key,
            "trading_day": active.trading_day,
            "session_generation_id": active.session_generation_id,
            "dispatch_front_id": active.dispatch_front_id,
            "dispatch_session_id": active.dispatch_session_id,
            "source_tags": {
                "source_instance_id": active.source_instance_id,
                "native_client_epoch": active.native_client_epoch,
                "native_api_source_id": active.native_api_source_id,
                "native_spi_source_id": active.native_spi_source_id,
                "native_api_generation": active.native_api_generation,
                "connection_generation": active.source_connection_generation,
            },
            "source_high_watermark": active.source_high_watermark,
        }
        if (
            command.account_key != active.account_key
            or command.scope_key != active.scope_key
            or command.trading_day != active.trading_day
            or command.session_binding_sha256 != active.session_binding_sha256
            or _sha256(command.session_binding) != active.session_binding_sha256
            or command.session_binding != binding_payload
            or correlation.account_key != active.account_key
            or correlation.scope_key != active.scope_key
            or correlation.trading_day != active.trading_day
            or correlation.session_binding_sha256 != active.session_binding_sha256
            or correlation.session_generation_id != active.session_generation_id
            or correlation.dispatch_front_id != active.dispatch_front_id
            or correlation.dispatch_session_id != active.dispatch_session_id
        ):
            _reject()

    @staticmethod
    def _action_digest(command: Any, scope: CtpManagedActionScopeV1) -> str:
        correlation = command.correlation_key
        if (
            correlation is None
            or correlation.version != 2
            or correlation.command_id != command.command_id
            or correlation.operation != command.operation
            or correlation.native_request_id <= 0
            or command.request_payload_sha256 != _sha256(command.request_payload)
            or command.native_request_payload_sha256 != _sha256(command.native_request_payload)
        ):
            _reject()
        logical = dict(command.request_payload)
        native = dict(command.native_request_payload)
        if command.operation == "SUBMIT":
            if (
                correlation.native_action_ref is not None
                or "OrderActionRef" in logical
                or native != logical
            ):
                _reject()
            target = None
            order_ref = command.order_ref
        elif command.operation == "CANCEL":
            action_ref = correlation.native_action_ref
            if (
                type(action_ref) is not int
                or not 1 <= action_ref <= _MAX_NATIVE_INT
                or "OrderActionRef" in logical
                or native != dict(logical, OrderActionRef=action_ref)
            ):
                _reject()
            target = {
                "order_ref": command.cancel_target_order_ref,
                "exchange_id": command.cancel_target_exchange_id,
                "order_sys_id": command.cancel_target_order_sys_id,
                "front_id": command.cancel_target_front_id,
                "session_id": command.cancel_target_session_id,
            }
            request_target = {
                "OrderRef": command.cancel_target_order_ref,
                "ExchangeID": command.cancel_target_exchange_id,
                "OrderSysID": command.cancel_target_order_sys_id,
                "FrontID": command.cancel_target_front_id,
                "SessionID": command.cancel_target_session_id,
            }
            if (
                type(request_target["OrderRef"]) is not str
                or not request_target["OrderRef"]
                or not request_target["OrderRef"].isascii()
                or type(request_target["ExchangeID"]) is not str
                or not request_target["ExchangeID"]
                or not request_target["ExchangeID"].isascii()
                or type(request_target["OrderSysID"]) is not str
                or not request_target["OrderSysID"]
                or not request_target["OrderSysID"].isascii()
                or type(request_target["FrontID"]) is not int
                or request_target["FrontID"] <= 0
                or type(request_target["SessionID"]) is not int
                or request_target["SessionID"] <= 0
                or any(
                    type(logical.get(field)) is not type(value) or logical.get(field) != value
                    for field, value in request_target.items()
                )
            ):
                _reject()
            order_ref = command.cancel_target_order_ref
        else:
            _reject()
        if (
            type(correlation.native_request_id) is not int
            or not 1 <= correlation.native_request_id <= _MAX_NATIVE_INT
            or correlation.request_payload_sha256 != command.request_payload_sha256
            or correlation.native_request_payload_sha256 != command.native_request_payload_sha256
            or correlation.order_ref != order_ref
            or correlation.reservation_managed_intent_id != command.reservation_managed_intent_id
            or command.account_key != command.correlation_key.account_key
            or command.scope_key != command.correlation_key.scope_key
            or command.trading_day != command.correlation_key.trading_day
        ):
            _reject()
        if command.operation == "SUBMIT":
            if (
                type(command.order_ref) is not str
                or not command.order_ref.isascii()
                or any(
                    value is not None
                    for value in (
                        command.cancel_target_order_ref,
                        command.cancel_target_exchange_id,
                        command.cancel_target_order_sys_id,
                        command.cancel_target_front_id,
                        command.cancel_target_session_id,
                        correlation.cancel_target_exchange_id,
                        correlation.cancel_target_order_sys_id,
                        correlation.cancel_target_front_id,
                        correlation.cancel_target_session_id,
                    )
                )
            ):
                _reject()
        elif (
            type(command.cancel_target_order_ref) is not str
            or not command.cancel_target_order_ref.isascii()
            or type(command.cancel_target_exchange_id) is not str
            or not command.cancel_target_exchange_id.isascii()
            or type(command.cancel_target_order_sys_id) is not str
            or not command.cancel_target_order_sys_id.isascii()
            or type(command.cancel_target_front_id) is not int
            or command.cancel_target_front_id <= 0
            or type(command.cancel_target_session_id) is not int
            or command.cancel_target_session_id <= 0
            or command.cancel_target_exchange_id != correlation.cancel_target_exchange_id
            or command.cancel_target_order_sys_id != correlation.cancel_target_order_sys_id
            or command.cancel_target_front_id != correlation.cancel_target_front_id
            or command.cancel_target_session_id != correlation.cancel_target_session_id
        ):
            _reject()
        material = {
            "domain": _PERMIT_DOMAIN,
            "scope": scope.to_payload(),
            "scope_sha256": scope.digest,
            "account_key": command.account_key,
            "scope_key": command.scope_key,
            "trading_day": command.trading_day,
            "operation": command.operation,
            "command_id": command.command_id,
            "logical_request_sha256": command.request_payload_sha256,
            "managed_intent_id": command.reservation_managed_intent_id,
            "managed_action_id": correlation.managed_action_id,
            "runtime_order_id": correlation.runtime_order_id,
            "order_ref": order_ref,
            "native_request_id": correlation.native_request_id,
            "cancel_target": target,
            "session_binding_sha256": command.session_binding_sha256,
            "session_generation_id": correlation.session_generation_id,
            "dispatch_front_id": correlation.dispatch_front_id,
            "dispatch_session_id": correlation.dispatch_session_id,
        }
        return _sha256(material)


class RejectingCtpManagedActionAuthorityVerifier:
    """Default factory result when no complete deployment trust bundle exists."""

    def verify_action(self, command: Any, *, now_ns: int) -> Any:
        del command, now_ns
        _reject()


def default_ctp_managed_action_authority_verifier() -> RejectingCtpManagedActionAuthorityVerifier:
    """Return a permanently rejecting verifier; no runtime trust is installed."""

    return RejectingCtpManagedActionAuthorityVerifier()


__all__ = [
    "CtpManagedActionAuthorityAdapter",
    "CtpManagedActionAuthorityError",
    "CtpManagedActionPermitV1",
    "CtpManagedActionRevocationSnapshot",
    "CtpManagedActionScopeV1",
    "CtpManagedActionWriterFenceSnapshot",
    "CtpPinnedEd25519ActionKey",
    "PinnedEd25519CtpActionPermitVerifier",
    "RejectingCtpManagedActionAuthorityVerifier",
    "default_ctp_managed_action_authority_verifier",
]
