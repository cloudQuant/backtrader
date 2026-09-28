"""Lease-bound, read-only tick handoff for managed SimNow consumers.

This module deliberately does not create a Store, native client, subscription,
or Backtrader Feed. A caller that already owns an authenticated MD stream may
adapt that stream to :class:`ManagedCtpMdTickSource`; this bridge pins its
selected scope and only yields strictly typed, fresh ticks from that scope.

The bridge is an adapter contract, not a provider authorization boundary. The
source must remain owned by the managed runtime which owns the account lease.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

from .ctp_simnow_managed_operator import CtpSimNowManagedScopeSelection
from .ctp_simnow_managed_runtime import CtpSimNowNativeReadiness


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CtpSimNowManagedMdBridgeError(ValueError):
    """Redacted fail-closed error from the managed MD tick bridge."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ManagedCtpMdLeaseSnapshot:
    """Owner-issued snapshot of one account-lease tenure.

    ``lease_generation`` must be a positive integer from an owner-maintained,
    strictly increasing per-account sequence. The owner must advance it after
    any lease loss, persist it across restarts, and never revive an old source
    after that loss, even if the same account later reacquires a lease. This
    bridge checks that contract but cannot independently authenticate the
    owner's implementation.
    """

    account_fingerprint_sha256: str
    lease_generation: int
    active: bool


@dataclass(frozen=True)
class ManagedCtpMdSourceIdentity:
    """Identity snapshot for one acknowledged stream and its readiness tick.

    The source adapter must take the generation, sequence, event-time and
    receive-time watermarks from the same MD client generation whose exact
    subscription ACK and first tick produced ``CtpSimNowNativeReadiness``.
    ``lease_generation`` comes from the managed owner; it is not caller-chosen
    and strictly increases on every lease grant after any prior loss.
    """

    config_digest: str
    registration_digest: str
    account_fingerprint_sha256: str
    lease_generation: int
    md_front: str
    td_front: str
    instrument_id: str
    exchange_id: str
    connection_generation: int
    subscription_epoch: int
    subscription_instrument_id: str
    subscription_acknowledged: bool
    first_tick_observed: bool
    ready_tick_sequence: int
    ready_event_timestamp: float
    ready_received_monotonic_ns: int


@dataclass(frozen=True)
class ManagedCtpMdTick:
    """Normalized single-instrument tick from the pinned managed MD stream.

    ``sequence`` must be greater than ``identity.ready_tick_sequence``; the
    readiness tick is used only as a watermark and is never re-emitted.
    """

    identity: ManagedCtpMdSourceIdentity
    sequence: int
    event_timestamp: float
    received_monotonic_ns: int
    instrument_id: str
    exchange_id: str
    last_price: float
    volume_delta: float
    bid_price: float
    ask_price: float
    bid_volume: float
    ask_volume: float
    trading_day: str = ""
    action_day: str = ""
    update_time: str = ""
    update_millisec: int = 0
    stale: bool = False
    stale_reason: str = ""


class ManagedCtpMdTickSource(Protocol):
    """Read-only view supplied by the owner of an already-started MD client."""

    @property
    def identity(self) -> ManagedCtpMdSourceIdentity:
        """Return the current front/account/instrument/generation snapshot."""

    @property
    def lease_snapshot(self) -> ManagedCtpMdLeaseSnapshot:
        """Return owner-issued active state and a non-reusable lease token.

        The owner must issue a strictly increasing per-account generation and
        permanently invalidate an old source after lease loss. Boolean-only
        checks do not satisfy this protocol. The snapshot and
        ``identity.lease_generation`` must name the same lease tenure.
        """

    def poll_tick(self) -> Optional[ManagedCtpMdTick]:
        """Return the next normalized tick without starting or subscribing."""


def _reject(reason: str) -> None:
    raise CtpSimNowManagedMdBridgeError(reason)


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _validate_lease_snapshot(
    snapshot: object, account_fingerprint_sha256: str
) -> ManagedCtpMdLeaseSnapshot:
    if type(snapshot) is not ManagedCtpMdLeaseSnapshot:
        _reject("managed_md_lease_snapshot_unavailable")
    assert isinstance(snapshot, ManagedCtpMdLeaseSnapshot)
    if (
        type(snapshot.account_fingerprint_sha256) is not str
        or not _SHA256_RE.fullmatch(snapshot.account_fingerprint_sha256)
        or type(snapshot.lease_generation) is not int
        or snapshot.lease_generation <= 0
        or type(snapshot.active) is not bool
    ):
        _reject("managed_md_lease_snapshot_invalid")
    if (
        snapshot.account_fingerprint_sha256 != account_fingerprint_sha256
        or snapshot.active is not True
    ):
        _reject("managed_md_account_lease_lost")
    return snapshot


def _read_lease_snapshot(
    source: ManagedCtpMdTickSource, account_fingerprint_sha256: str
) -> ManagedCtpMdLeaseSnapshot:
    try:
        snapshot = source.lease_snapshot
    except Exception:
        _reject("managed_md_lease_snapshot_unavailable")
    return _validate_lease_snapshot(snapshot, account_fingerprint_sha256)


def _validate_identity(identity: object) -> ManagedCtpMdSourceIdentity:
    if type(identity) is not ManagedCtpMdSourceIdentity:
        _reject("managed_md_source_identity_invalid")
    assert isinstance(identity, ManagedCtpMdSourceIdentity)
    for value in (
        identity.config_digest,
        identity.registration_digest,
        identity.account_fingerprint_sha256,
    ):
        if type(value) is not str or not _SHA256_RE.fullmatch(value):
            _reject("managed_md_source_identity_invalid")
    if type(identity.lease_generation) is not int or identity.lease_generation <= 0:
        _reject("managed_md_source_identity_invalid")
    for value in (
        identity.md_front,
        identity.td_front,
        identity.instrument_id,
        identity.exchange_id,
        identity.subscription_instrument_id,
    ):
        if type(value) is not str or not value or value != value.strip():
            _reject("managed_md_source_identity_invalid")
    if (
        type(identity.connection_generation) is not int
        or identity.connection_generation <= 0
        or type(identity.subscription_epoch) is not int
        or identity.subscription_epoch <= 0
        or type(identity.ready_tick_sequence) is not int
        or identity.ready_tick_sequence <= 0
        or not _finite_number(identity.ready_event_timestamp)
        or float(identity.ready_event_timestamp) <= 0
        or type(identity.ready_received_monotonic_ns) is not int
        or identity.ready_received_monotonic_ns <= 0
        or type(identity.subscription_acknowledged) is not bool
        or identity.subscription_acknowledged is not True
        or type(identity.first_tick_observed) is not bool
        or identity.first_tick_observed is not True
        or identity.subscription_instrument_id != identity.instrument_id
    ):
        _reject("managed_md_source_not_ready")
    return identity


class CtpSimNowManagedMdTickBridge:
    """Pin and poll a lease-owned MD source without taking client ownership.

    Construction requires native readiness for the exact selected scope and
    a source identity that proves an exact subscription ACK plus a first tick.
    Every poll rechecks the account lease and complete source identity before
    and after reading. A source fault, scope/generation change, malformed tick,
    or stale/out-of-order tick poisons the bridge permanently.

    ``poll_tick`` returns a typed event for a future Feed adapter. It does not
    create or mutate a ``BtApiFeed`` because that Feed currently owns a Store
    lifecycle and cannot safely adopt the already-started managed MD client.
    """

    def __init__(
        self,
        selection: CtpSimNowManagedScopeSelection,
        readiness: CtpSimNowNativeReadiness,
        source: ManagedCtpMdTickSource,
    ) -> None:
        self._selection = selection
        self._source = source
        self._lock = threading.Lock()
        self._closed = False
        self._fault: Optional[str] = None
        self._last_sequence = 0
        self._last_event_timestamp = 0.0
        self._last_received_monotonic_ns = 0

        if type(readiness) is not CtpSimNowNativeReadiness:
            _reject("managed_md_readiness_required")
        try:
            matches = readiness.matches(selection)
        except Exception:
            matches = False
        if matches is not True:
            _reject("managed_md_readiness_scope_mismatch")

        try:
            registration = selection.execution_registration
            account_fingerprint = registration.account_fingerprint_sha256
            lease_snapshot = _read_lease_snapshot(source, account_fingerprint)
            expected = {
                "config_digest": selection.config_digest,
                "registration_digest": registration.digest,
                "account_fingerprint_sha256": account_fingerprint,
                "md_front": registration.md_front,
                "td_front": registration.td_front,
                "instrument_id": registration.instrument_id,
                "exchange_id": registration.exchange_id,
            }
            source_identity = _validate_identity(source.identity)
        except CtpSimNowManagedMdBridgeError:
            raise
        except Exception:
            _reject("managed_md_source_unavailable")
        if any(getattr(source_identity, key) != value for key, value in expected.items()):
            _reject("managed_md_source_scope_mismatch")
        if source_identity.lease_generation != lease_snapshot.lease_generation:
            _reject("managed_md_source_lease_generation_mismatch")

        self._identity = source_identity
        self._lease_generation = lease_snapshot.lease_generation
        self._last_sequence = source_identity.ready_tick_sequence
        self._last_event_timestamp = float(source_identity.ready_event_timestamp)
        self._last_received_monotonic_ns = source_identity.ready_received_monotonic_ns
        self._assert_source_current()

    @property
    def identity(self) -> ManagedCtpMdSourceIdentity:
        """Return the pinned identity for diagnostics and downstream binding."""

        with self._lock:
            self._require_usable()
            return self._identity

    def _require_usable(self) -> None:
        if self._fault is not None:
            _reject(self._fault)
        if self._closed:
            _reject("managed_md_bridge_closed")

    def _poison(self, reason: str) -> None:
        self._fault = reason
        _reject(reason)

    def _assert_source_current(self) -> None:
        self._require_usable()
        try:
            lease_snapshot = _read_lease_snapshot(
                self._source, self._identity.account_fingerprint_sha256
            )
            current = _validate_identity(self._source.identity)
        except CtpSimNowManagedMdBridgeError as exc:
            self._poison(exc.reason)
        except Exception:
            self._poison("managed_md_source_unavailable")
        if (
            lease_snapshot.lease_generation != self._lease_generation
            or current.lease_generation != self._lease_generation
        ):
            self._poison("managed_md_account_lease_changed")
        if current != self._identity:
            self._poison("managed_md_source_generation_or_scope_changed")

    def _validate_tick(self, tick: object) -> ManagedCtpMdTick:
        if type(tick) is not ManagedCtpMdTick:
            self._poison("managed_md_tick_shape_unknown")
        assert isinstance(tick, ManagedCtpMdTick)
        if tick.identity != self._identity:
            self._poison("managed_md_tick_scope_or_generation_mismatch")
        if (
            tick.instrument_id != self._identity.instrument_id
            or tick.exchange_id != self._identity.exchange_id
        ):
            self._poison("managed_md_tick_instrument_mismatch")
        if (
            type(tick.sequence) is not int
            or tick.sequence <= self._last_sequence
            or not _finite_number(tick.event_timestamp)
            or float(tick.event_timestamp) <= 0
            or float(tick.event_timestamp) < self._last_event_timestamp
            or type(tick.received_monotonic_ns) is not int
            or tick.received_monotonic_ns <= self._last_received_monotonic_ns
            or tick.stale is not False
            or type(tick.stale_reason) is not str
            or tick.stale_reason != ""
        ):
            self._poison("managed_md_tick_stale_or_out_of_order")
        if (
            not _finite_number(tick.last_price)
            or float(tick.last_price) <= 0
            or not _finite_number(tick.volume_delta)
            or float(tick.volume_delta) < 0
            or not _finite_number(tick.bid_price)
            or float(tick.bid_price) <= 0
            or not _finite_number(tick.ask_price)
            or float(tick.ask_price) <= 0
            or float(tick.bid_price) > float(tick.ask_price)
            or not _finite_number(tick.bid_volume)
            or float(tick.bid_volume) < 0
            or not _finite_number(tick.ask_volume)
            or float(tick.ask_volume) < 0
            or type(tick.update_millisec) is not int
            or not 0 <= tick.update_millisec <= 999
            or any(
                type(value) is not str
                for value in (tick.trading_day, tick.action_day, tick.update_time)
            )
        ):
            self._poison("managed_md_tick_fields_invalid")
        self._last_sequence = tick.sequence
        self._last_event_timestamp = float(tick.event_timestamp)
        self._last_received_monotonic_ns = tick.received_monotonic_ns
        return tick

    def poll_tick(self) -> Optional[ManagedCtpMdTick]:
        """Yield one validated tick, or ``None`` when the source is idle."""

        with self._lock:
            self._assert_source_current()
            try:
                tick = self._source.poll_tick()
            except Exception:
                self._poison("managed_md_source_poll_failed")
            self._assert_source_current()
            if tick is None:
                return None
            return self._validate_tick(tick)

    def retire(self) -> None:
        """Stop yielding locally; the managed runtime retains client ownership."""

        with self._lock:
            if self._fault is None:
                self._closed = True


__all__ = [
    "CtpSimNowManagedMdBridgeError",
    "CtpSimNowManagedMdTickBridge",
    "ManagedCtpMdLeaseSnapshot",
    "ManagedCtpMdSourceIdentity",
    "ManagedCtpMdTick",
    "ManagedCtpMdTickSource",
]
