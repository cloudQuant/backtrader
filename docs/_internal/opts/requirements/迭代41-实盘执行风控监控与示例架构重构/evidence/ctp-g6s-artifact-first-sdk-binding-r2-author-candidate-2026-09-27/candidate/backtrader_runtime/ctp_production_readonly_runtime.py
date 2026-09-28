"""Non-authorizing CTP production read-only composition contract.

This module joins the existing parser-sealed production config pin to one
read-only session. It has no import-time CTP SDK dependency, provider default,
inventory entry, CLI route, or execution method. The returned evidence
identifies completion of the session protocol only; it cannot attest that the
adapter was an approved SDK build or a real provider session.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import hmac
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, NoReturn, Protocol

from .ctp_preflight import REQUIRED_CTP_READ_ONLY_QUERIES
from .ctp_front_pair_probe import CtpFrontPairProbeError, select_ctp_front_pair
from .ctp_production_readonly_admission import (
    CtpProductionReadOnlyAdmissionError,
    CtpProductionReadOnlyConfigBinding,
    CtpProductionReadOnlyRegistration,
    require_ctp_production_readonly_config_binding,
)
from .config import RuntimeConfig
from .registry import RuntimeRegistry


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRADING_DAY_RE = re.compile(r"^[0-9]{8}$")
_MAX_SESSION_SECONDS = 60.0
_WRITE_COUNTERS = ("settlement_confirm", "order_insert", "order_action")
_LOCAL_TD_FRONT_EVIDENCE = "local_sdk_on_front_connected_callback"


class CtpProductionReadOnlyRuntimeError(ValueError):
    """Redacted failure of the injected production read-only contract."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> NoReturn:
    raise CtpProductionReadOnlyRuntimeError(reason, message) from None


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_observation", "invalid production {0}".format(name))
    return value


def _trading_day(value: Any) -> str:
    if type(value) is not str or _TRADING_DAY_RE.fullmatch(value) is None:
        _reject("invalid_session_identity", "invalid production CTP trading day")
    try:
        _datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        _reject("invalid_session_identity", "invalid production CTP trading day")
    return value


def _deadline(valid_until: float, monotonic_deadline: float) -> None:
    if time.time() >= valid_until or time.monotonic() >= monotonic_deadline:
        _reject("session_deadline_expired", "production read-only session deadline expired")


@dataclass(frozen=True)
class CtpProductionReadOnlySessionRequest:
    """Non-secret scope passed to a reviewed production read-only adapter."""

    environment: str
    account_binding_sha256: str = field(repr=False)
    front_pair_set_sha256: str = field(repr=False)
    md_front_sha256: str = field(repr=False)
    td_front_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    valid_until: float

    def __post_init__(self) -> None:
        if self.environment != "production":
            _reject("environment_mismatch", "production session requires production scope")
        object.__setattr__(
            self, "account_binding_sha256", _digest(self.account_binding_sha256, "account pin")
        )
        object.__setattr__(
            self,
            "front_pair_set_sha256",
            _digest(self.front_pair_set_sha256, "front-pair set digest"),
        )
        object.__setattr__(self, "md_front_sha256", _digest(self.md_front_sha256, "MD front pin"))
        object.__setattr__(self, "td_front_sha256", _digest(self.td_front_sha256, "TD front pin"))
        if (
            type(self.instrument_id) is not str
            or type(self.exchange_id) is not str
            or type(self.hedge_flag) is not str
            or self.hedge_flag not in ("1", "2", "3")
        ):
            _reject("invalid_request", "invalid production CTP instrument scope")
        if type(self.valid_until) not in (int, float) or not math.isfinite(self.valid_until):
            _reject("invalid_request", "invalid production read-only deadline")


@dataclass(frozen=True)
class CtpProductionReadOnlySessionIdentity:
    """Non-secret identity and bounded local front-binding evidence."""

    account_binding_sha256: str = field(repr=False)
    trading_day: str
    connection_generation: int
    md_front_sha256: str = field(repr=False)
    td_front_sha256: str = field(repr=False)
    td_front_binding_evidence: str
    environment: str = "production"

    def __post_init__(self) -> None:
        if self.environment != "production":
            _reject("environment_mismatch", "production session reported another environment")
        object.__setattr__(
            self,
            "account_binding_sha256",
            _digest(self.account_binding_sha256, "session account binding"),
        )
        object.__setattr__(self, "md_front_sha256", _digest(self.md_front_sha256, "MD front pin"))
        object.__setattr__(self, "td_front_sha256", _digest(self.td_front_sha256, "TD front pin"))
        if self.td_front_binding_evidence != _LOCAL_TD_FRONT_EVIDENCE:
            _reject("invalid_session_identity", "missing local CTP TD-front callback evidence")
        object.__setattr__(self, "trading_day", _trading_day(self.trading_day))
        if (
            type(self.connection_generation) is not int
            or self.connection_generation <= 0
            or self.connection_generation > (2**63 - 1)
        ):
            _reject("invalid_session_identity", "invalid production CTP session generation")


def _snapshot_digest_payload(
    identity: CtpProductionReadOnlySessionIdentity,
    query_digests: tuple[tuple[str, str], ...],
    instrument_id: str,
    exchange_id: str,
    hedge_flag: str,
    native_certificate_sha256: str | None,
    market_data_observation: "CtpProductionReadOnlyMarketDataObservation | None" = None,
) -> bytes:
    value = {
        "account_binding_sha256": identity.account_binding_sha256,
        "connection_generation": identity.connection_generation,
        "environment": identity.environment,
        "exchange_id": exchange_id,
        "hedge_flag": hedge_flag,
        "instrument_id": instrument_id,
        "md_front_sha256": identity.md_front_sha256,
        "query_digests": [[name, digest] for name, digest in query_digests],
        "td_front_sha256": identity.td_front_sha256,
        "td_front_binding_evidence": identity.td_front_binding_evidence,
        "trading_day": identity.trading_day,
    }
    if native_certificate_sha256 is not None:
        value["native_certificate_sha256"] = native_certificate_sha256
    if market_data_observation is not None:
        value["market_data_observation"] = market_data_observation.as_public_dict()
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


@dataclass(frozen=True)
class CtpProductionReadOnlyMarketDataObservation:
    """Bounded local MD callback evidence for one exact production contract.

    This records the local SDK's login, subscription acknowledgement and a
    matching post-ack tick. It does not attest the remote endpoint's identity.
    """

    md_front_sha256: str = field(repr=False)
    account_binding_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    tick_observation_count: int
    connection_generation: int
    client_stop_returned: bool
    native_join_pending: bool
    market_login_ready: bool = True
    subscription_acknowledged: bool = True
    remote_front_identity_verified: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "md_front_sha256", _digest(self.md_front_sha256, "MD front pin"))
        object.__setattr__(
            self, "account_binding_sha256", _digest(self.account_binding_sha256, "account pin")
        )
        if (
            type(self.instrument_id) is not str
            or not self.instrument_id
            or type(self.exchange_id) is not str
            or not self.exchange_id
            or type(self.tick_observation_count) is not int
            or self.tick_observation_count < 1
            or type(self.connection_generation) is not int
            or self.connection_generation <= 0
            or self.market_login_ready is not True
            or self.subscription_acknowledged is not True
            or self.client_stop_returned is not True
            or self.native_join_pending is not False
            or self.remote_front_identity_verified is not False
        ):
            _reject("invalid_market_data_observation", "invalid production CTP MD observation")

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "account_probe_lock_scope": "cooperating_probe_invocations_only",
            "account_scope": "redacted",
            "client_stop_returned": self.client_stop_returned,
            "connection_generation": self.connection_generation,
            "exchange_id": self.exchange_id,
            "first_tick_observed": self.tick_observation_count > 0,
            "instrument_id": self.instrument_id,
            "market_login_ready": self.market_login_ready,
            "md_front_sha256": self.md_front_sha256,
            "native_join_pending": self.native_join_pending,
            "remote_front_identity_verified": self.remote_front_identity_verified,
            "subscription_acknowledged": self.subscription_acknowledged,
            "tick_observation_count": self.tick_observation_count,
        }


@dataclass(frozen=True)
class CtpProductionReadOnlyQuerySnapshot:
    """Digest-only summary of seven TD reads and optional bounded MD evidence."""

    identity: CtpProductionReadOnlySessionIdentity
    query_digests: tuple[tuple[str, str], ...]
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    snapshot_sha256: str
    native_certificate_sha256: str | None = None
    market_data_observation: CtpProductionReadOnlyMarketDataObservation | None = None

    def __post_init__(self) -> None:
        if type(self.identity) is not CtpProductionReadOnlySessionIdentity:
            _reject("invalid_observation", "invalid production query identity")
        if type(self.query_digests) not in (tuple, list):
            _reject("invalid_observation", "invalid production query digest set")
        normalized = []
        for pair in self.query_digests:
            if type(pair) not in (tuple, list) or len(pair) != 2:
                _reject("invalid_observation", "invalid production query digest pair")
            name, value = pair
            if type(name) is not str or name not in REQUIRED_CTP_READ_ONLY_QUERIES:
                _reject("invalid_observation", "unexpected production CTP query")
            normalized.append((name, _digest(value, "query digest")))
        if tuple(sorted(name for name, _ in normalized)) != tuple(
            sorted(REQUIRED_CTP_READ_ONLY_QUERIES)
        ):
            _reject("incomplete_query_set", "production CTP query set is incomplete")
        normalized_tuple = tuple(sorted(normalized))
        if (
            type(self.instrument_id) is not str
            or not self.instrument_id
            or type(self.exchange_id) is not str
            or not self.exchange_id
            or type(self.hedge_flag) is not str
            or self.hedge_flag not in ("1", "2", "3")
        ):
            _reject("invalid_observation", "invalid production query instrument scope")
        native_certificate_sha256 = (
            None
            if self.native_certificate_sha256 is None
            else _digest(self.native_certificate_sha256, "native certificate digest")
        )
        market_data_observation = self.market_data_observation
        if market_data_observation is not None:
            if type(market_data_observation) is not CtpProductionReadOnlyMarketDataObservation:
                _reject("invalid_observation", "invalid production MD observation")
            if (
                market_data_observation.account_binding_sha256
                != self.identity.account_binding_sha256
                or market_data_observation.md_front_sha256 != self.identity.md_front_sha256
                or market_data_observation.instrument_id != self.instrument_id
                or market_data_observation.exchange_id != self.exchange_id
            ):
                _reject("market_data_scope_mismatch", "production MD observation scope changed")
        expected = hashlib.sha256(
            _snapshot_digest_payload(
                self.identity,
                normalized_tuple,
                self.instrument_id,
                self.exchange_id,
                self.hedge_flag,
                native_certificate_sha256,
                market_data_observation,
            )
        ).hexdigest()
        actual = _digest(self.snapshot_sha256, "snapshot digest")
        if not hmac.compare_digest(expected, actual):
            _reject("snapshot_digest_mismatch", "production query digest does not match summary")
        object.__setattr__(self, "query_digests", normalized_tuple)
        object.__setattr__(self, "snapshot_sha256", actual)
        object.__setattr__(self, "native_certificate_sha256", native_certificate_sha256)
        object.__setattr__(self, "market_data_observation", market_data_observation)

    @classmethod
    def from_query_digests(
        cls,
        identity: CtpProductionReadOnlySessionIdentity,
        query_digests: tuple[tuple[str, str], ...],
        *,
        instrument_id: str,
        exchange_id: str,
        hedge_flag: str,
        native_certificate_sha256: str | None = None,
        market_data_observation: CtpProductionReadOnlyMarketDataObservation | None = None,
    ) -> "CtpProductionReadOnlyQuerySnapshot":
        normalized = tuple(
            sorted((name, _digest(value, "query digest")) for name, value in query_digests)
        )
        digest = hashlib.sha256(
            _snapshot_digest_payload(
                identity,
                normalized,
                instrument_id,
                exchange_id,
                hedge_flag,
                native_certificate_sha256,
                market_data_observation,
            )
        ).hexdigest()
        return cls(
            identity=identity,
            query_digests=normalized,
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            hedge_flag=hedge_flag,
            snapshot_sha256=digest,
            native_certificate_sha256=native_certificate_sha256,
            market_data_observation=market_data_observation,
        )

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "account_scope": "redacted",
            "connection_generation": self.identity.connection_generation,
            "environment": self.identity.environment,
            "exchange_id": self.exchange_id,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "native_certificate_sha256": self.native_certificate_sha256,
            "market_data_observation": (
                None
                if self.market_data_observation is None
                else self.market_data_observation.as_public_dict()
            ),
            "query_digests": self.query_digests,
            "snapshot_sha256": self.snapshot_sha256,
            "trading_day": self.identity.trading_day,
        }


class CtpProductionReadOnlySession(Protocol):
    """Narrow adapter surface with no order, arm, cancel, or execution call."""

    def read_identity(self) -> CtpProductionReadOnlySessionIdentity:
        ...

    def read_query_snapshot(self) -> CtpProductionReadOnlyQuerySnapshot:
        ...

    def read_write_counters(self) -> Mapping[str, int]:
        ...

    def close_read_only(self) -> None:
        ...


class CtpProductionReadOnlySessionFactory(Protocol):
    """Injected production adapter; no concrete provider implementation exists here."""

    def open_read_only(
        self, request: CtpProductionReadOnlySessionRequest
    ) -> CtpProductionReadOnlySession:
        ...


@dataclass(frozen=True)
class CtpProductionReadOnlyRuntimeObservation:
    """Redacted protocol result that is explicitly not provider acceptance."""

    binding: CtpProductionReadOnlyConfigBinding = field(repr=False)
    trading_day: str
    connection_generation: int
    query_snapshot: CtpProductionReadOnlyQuerySnapshot
    session_factory_invoked: bool = True
    evidence_class: str = field(default="INJECTED_SESSION_PROTOCOL", init=False)
    provider_session_verified: bool = field(default=False, init=False)
    remote_front_identity_verified: bool = field(default=False, init=False)
    provider_read_authorized: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)
    external_write_requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if type(self.binding) is not CtpProductionReadOnlyConfigBinding:
            _reject("invalid_observation", "missing production config binding")
        if type(self.query_snapshot) is not CtpProductionReadOnlyQuerySnapshot:
            _reject("invalid_observation", "invalid production read-only snapshot")
        object.__setattr__(self, "trading_day", _trading_day(self.trading_day))
        if (
            self.session_factory_invoked is not True
            or self.query_snapshot.identity.trading_day != self.trading_day
            or self.query_snapshot.identity.connection_generation != self.connection_generation
            or self.query_snapshot.identity.account_binding_sha256
            != self.binding.account_binding_sha256
            or self.query_snapshot.identity.environment != self.binding.environment
            or self.provider_session_verified is not False
            or self.remote_front_identity_verified is not False
            or self.provider_read_authorized is not False
            or self.credential_access_authorized is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
            or self.order_submission_authorized is not False
            or self.cancellation_authorized is not False
            or self.arming_authorized is not False
            or self.external_write_requests != 0
        ):
            _reject("invalid_observation", "production read-only result cannot grant authority")

    def __bool__(self) -> bool:
        raise TypeError("production read-only observation is non-authorizing evidence")

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "connection_generation": self.connection_generation,
            "credential_access_authorized": self.credential_access_authorized,
            "evidence_class": self.evidence_class,
            "execution_authorized": self.execution_authorized,
            "external_write_requests": self.external_write_requests,
            "external_writes_authorized": self.external_writes_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "provider": "ctp",
            "provider_read_authorized": self.provider_read_authorized,
            "provider_session_verified": self.provider_session_verified,
            "md_front_evidence": (
                "local_sdk_login_subscription_post_ack_tick"
                if self.query_snapshot.market_data_observation is not None
                else "sealed_config_pin_only"
            ),
            "market_data_observation": (
                None
                if self.query_snapshot.market_data_observation is None
                else self.query_snapshot.market_data_observation.as_public_dict()
            ),
            "remote_front_identity_verified": self.remote_front_identity_verified,
            "td_front_binding_evidence": self.query_snapshot.identity.td_front_binding_evidence,
            "query_snapshot": self.query_snapshot.as_public_dict(),
            "registration_digest": self.binding.registration_digest,
            "runtime_id": self.binding.runtime_id,
            "session_factory_invoked": self.session_factory_invoked,
            "strategy_id": self.binding.strategy_id,
            "trading_day": self.trading_day,
        }


def _require_zero_writes(session: Any) -> None:
    try:
        reader = getattr(session, "read_write_counters", None)
        counts = reader() if callable(reader) else None
    except Exception:
        counts = None
    if (
        type(counts) is not dict
        or set(counts) != set(_WRITE_COUNTERS)
        or any(type(counts[name]) is not int or counts[name] != 0 for name in _WRITE_COUNTERS)
    ):
        _reject(
            "write_counter_rejected", "production CTP write counters are unavailable or nonzero"
        )


def run_ctp_production_readonly_preflight(
    *,
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionReadOnlyRegistration,
    session_factory: CtpProductionReadOnlySessionFactory,
    session_ttl_seconds: float = _MAX_SESSION_SECONDS,
) -> CtpProductionReadOnlyRuntimeObservation:
    """Check the exact production pin, then run one injected seven-query session.

    This contract is deliberately not wired into ``bt-runtime`` or the default
    registry. The injected factory must be independently reviewed before use;
    this function verifies its output shape and zero-write counters but does
    not establish SDK artifact provenance or real-provider identity.
    """

    try:
        binding = require_ctp_production_readonly_config_binding(
            config, registry, admission_registration
        )
    except CtpProductionReadOnlyAdmissionError as error:
        if error.reason == "legacy_front_pin_incompatible_with_multi_pair_config":
            _reject(
                "legacy_front_pin_incompatible_with_multi_pair_config",
                "multi-pair production config requires config-only front selection",
            )
        _reject("config_binding_rejected", "sealed CTP production config pin was rejected")
    except Exception:
        _reject("config_binding_rejected", "sealed CTP production config pin was rejected")
    try:
        selection = select_ctp_front_pair(
            tuple(
                {"md_front": md_front, "td_front": td_front}
                for md_front, td_front in binding.front_pairs
            ),
            timeout_seconds=2.0,
            max_pairs=8,
            repeated_samples=3,
        )
        binding = require_ctp_production_readonly_config_binding(
            config,
            registry,
            admission_registration,
            selected_front_pair=(
                selection.pair.md_front,
                selection.pair.td_front,
            ),
        )
    except (CtpFrontPairProbeError, CtpProductionReadOnlyAdmissionError):
        _reject("front_probe_rejected", "configured CTP production fronts could not be selected")
    except Exception:
        _reject("front_probe_rejected", "configured CTP production fronts could not be selected")
    if binding.md_front is None or binding.td_front is None:
        _reject("front_selection_required", "production CTP fronts must be selected from config")
    if type(session_ttl_seconds) not in (int, float) or not math.isfinite(session_ttl_seconds):
        _reject("invalid_session_deadline", "invalid production CTP session lifetime")
    if session_ttl_seconds <= 0 or session_ttl_seconds > _MAX_SESSION_SECONDS:
        _reject("invalid_session_deadline", "production CTP session lifetime is outside policy")
    try:
        open_read_only = getattr(session_factory, "open_read_only", None)
    except Exception:
        open_read_only = None
    if not callable(open_read_only):
        _reject("session_factory_required", "an injected production read-only adapter is required")

    valid_until = time.time() + float(session_ttl_seconds)
    monotonic_deadline = time.monotonic() + float(session_ttl_seconds)
    request = CtpProductionReadOnlySessionRequest(
        environment=binding.environment,
        account_binding_sha256=binding.account_binding_sha256,
        front_pair_set_sha256=binding.front_pair_set_sha256,
        md_front_sha256=hashlib.sha256(binding.md_front.encode("utf-8")).hexdigest(),
        td_front_sha256=hashlib.sha256(binding.td_front.encode("utf-8")).hexdigest(),
        instrument_id=binding.instrument_id,
        exchange_id=binding.exchange_id,
        hedge_flag=binding.hedge_flag,
        valid_until=valid_until,
    )
    session = None
    result = None
    error: CtpProductionReadOnlyRuntimeError | None = None
    close_read_only = None
    try:
        _deadline(valid_until, monotonic_deadline)
        try:
            session = open_read_only(request)
        except Exception:
            _reject("session_open_failed", "unable to open injected production read-only session")
        if session is None:
            _reject("session_open_failed", "injected production adapter returned no session")
        try:
            close_read_only = getattr(session, "close_read_only", None)
        except Exception:
            close_read_only = None
        if not callable(close_read_only):
            _reject("invalid_session", "production read-only session has no close operation")

        _require_zero_writes(session)
        _deadline(valid_until, monotonic_deadline)
        try:
            identity_before = session.read_identity()
        except Exception:
            _reject("session_identity_unavailable", "production session identity is unavailable")
        if type(identity_before) is not CtpProductionReadOnlySessionIdentity:
            _reject("invalid_session_identity", "production session returned an invalid identity")
        if (
            identity_before.account_binding_sha256 != binding.account_binding_sha256
            or identity_before.environment != binding.environment
            or identity_before.md_front_sha256 != request.md_front_sha256
            or identity_before.td_front_sha256 != request.td_front_sha256
        ):
            _reject("session_identity_mismatch", "production session identity does not match pin")
        _deadline(valid_until, monotonic_deadline)
        try:
            snapshot = session.read_query_snapshot()
        except Exception:
            _reject("query_snapshot_unavailable", "production CTP read-only queries failed")
        if type(snapshot) is not CtpProductionReadOnlyQuerySnapshot:
            _reject(
                "invalid_query_snapshot", "production session returned an invalid query summary"
            )
        if (
            snapshot.identity != identity_before
            or snapshot.instrument_id != request.instrument_id
            or snapshot.exchange_id != request.exchange_id
            or snapshot.hedge_flag != request.hedge_flag
        ):
            _reject("snapshot_identity_mismatch", "production query identity changed")
        _require_zero_writes(session)
        _deadline(valid_until, monotonic_deadline)
        try:
            identity_after = session.read_identity()
        except Exception:
            _reject("session_identity_unavailable", "production session identity is unavailable")
        if identity_after != identity_before:
            _reject("session_identity_changed", "production session identity changed during query")
        result = CtpProductionReadOnlyRuntimeObservation(
            binding=binding,
            trading_day=identity_before.trading_day,
            connection_generation=identity_before.connection_generation,
            query_snapshot=snapshot,
        )
    except CtpProductionReadOnlyRuntimeError as caught:
        error = caught
    except Exception:
        error = CtpProductionReadOnlyRuntimeError(
            "read_only_session_failed", "production CTP read-only session failed"
        )
    finally:
        if callable(close_read_only):
            try:
                close_read_only()
            except Exception:
                if error is None:
                    error = CtpProductionReadOnlyRuntimeError(
                        "session_close_failed", "production CTP session did not close cleanly"
                    )
    if session is not None and error is None:
        try:
            _require_zero_writes(session)
            _deadline(valid_until, monotonic_deadline)
        except CtpProductionReadOnlyRuntimeError as caught:
            error = caught
        except Exception:
            error = CtpProductionReadOnlyRuntimeError(
                "session_close_failed", "production CTP session did not close cleanly"
            )
    if error is not None:
        raise error
    if result is None:
        _reject("read_only_session_failed", "production CTP read-only session failed")
    return result


__all__ = [
    "CtpProductionReadOnlyMarketDataObservation",
    "CtpProductionReadOnlyQuerySnapshot",
    "CtpProductionReadOnlyRuntimeError",
    "CtpProductionReadOnlyRuntimeObservation",
    "CtpProductionReadOnlySession",
    "CtpProductionReadOnlySessionFactory",
    "CtpProductionReadOnlySessionIdentity",
    "CtpProductionReadOnlySessionRequest",
    "run_ctp_production_readonly_preflight",
]
