from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader_runtime.ctp_simnow_managed_md_bridge import (
    CtpSimNowManagedMdBridgeError,
    CtpSimNowManagedMdTickBridge,
    ManagedCtpMdLeaseSnapshot,
    ManagedCtpMdSourceIdentity,
    ManagedCtpMdTick,
)
from backtrader_runtime.ctp_simnow_managed_runtime import CtpSimNowNativeReadiness


_CONFIG = "a" * 64
_REGISTRATION = "b" * 64
_ACCOUNT = "c" * 64
_MD_FRONT = "tcp://127.0.0.1:11001"
_TD_FRONT = "tcp://127.0.0.1:12001"
_INSTRUMENT = "rb2701"
_EXCHANGE = "SHFE"


def _scope():
    registration = SimpleNamespace(
        digest=_REGISTRATION,
        account_fingerprint_sha256=_ACCOUNT,
        md_front=_MD_FRONT,
        td_front=_TD_FRONT,
        instrument_id=_INSTRUMENT,
        exchange_id=_EXCHANGE,
    )
    selection = SimpleNamespace(
        execution_registration=registration,
        config_digest=_CONFIG,
    )
    readiness = CtpSimNowNativeReadiness(
        config_digest=_CONFIG,
        registration_digest=_REGISTRATION,
        account_fingerprint_sha256=_ACCOUNT,
        md_front=_MD_FRONT,
        td_front=_TD_FRONT,
        td_ready=True,
        md_ready=True,
    )
    return selection, readiness


def _identity(**changes):
    values = {
        "config_digest": _CONFIG,
        "registration_digest": _REGISTRATION,
        "account_fingerprint_sha256": _ACCOUNT,
        "lease_generation": 7,
        "md_front": _MD_FRONT,
        "td_front": _TD_FRONT,
        "instrument_id": _INSTRUMENT,
        "exchange_id": _EXCHANGE,
        "connection_generation": 7,
        "subscription_epoch": 3,
        "subscription_instrument_id": _INSTRUMENT,
        "subscription_acknowledged": True,
        "first_tick_observed": True,
        "ready_tick_sequence": 100,
        "ready_event_timestamp": 1_799_999_999.0,
        "ready_received_monotonic_ns": 9_000,
    }
    values.update(changes)
    return ManagedCtpMdSourceIdentity(**values)


def _tick(identity=None, **changes):
    values = {
        "identity": identity or _identity(),
        "sequence": 101,
        "event_timestamp": 1_800_000_000.0,
        "received_monotonic_ns": 10_000,
        "instrument_id": _INSTRUMENT,
        "exchange_id": _EXCHANGE,
        "last_price": 3500.0,
        "volume_delta": 1.0,
        "bid_price": 3499.0,
        "ask_price": 3501.0,
        "bid_volume": 2.0,
        "ask_volume": 3.0,
        "trading_day": "20260928",
        "action_day": "20260928",
        "update_time": "09:00:00",
        "update_millisec": 1,
        "stale": False,
        "stale_reason": "",
    }
    values.update(changes)
    return ManagedCtpMdTick(**values)


class _FakeLeaseOwnedSource:
    def __init__(self, identity, ticks=()):
        self.identity = identity
        self.ticks = list(ticks)
        self.lease_snapshot_reads = 0
        self.poll_calls = 0
        self.lease_active = True
        self.lease_generation = identity.lease_generation
        self.after_poll = None

    @property
    def lease_snapshot(self) -> ManagedCtpMdLeaseSnapshot:
        self.lease_snapshot_reads += 1
        return ManagedCtpMdLeaseSnapshot(
            account_fingerprint_sha256=_ACCOUNT,
            lease_generation=self.lease_generation,
            active=self.lease_active,
        )

    def poll_tick(self) -> Optional[ManagedCtpMdTick]:
        self.poll_calls += 1
        tick = self.ticks.pop(0) if self.ticks else None
        if self.after_poll is not None:
            self.after_poll()
        return tick

    def start(self):  # pragma: no cover - must never be called
        raise AssertionError("bridge must not start the source")

    def subscribe(self, *_args):  # pragma: no cover - must never be called
        raise AssertionError("bridge must not subscribe the source")

    def close(self):  # pragma: no cover - bridge must not own client lifecycle
        raise AssertionError("bridge must not close the source")


def _bridge(source=None, *, identity=None, readiness=None):
    selection, ready = _scope()
    return CtpSimNowManagedMdTickBridge(
        selection,
        readiness or ready,
        source or _FakeLeaseOwnedSource(identity or _identity()),
    )


def test_bridge_yields_only_new_ticks_and_leaves_source_lifecycle_owned_elsewhere():
    source_identity = _identity()
    source = _FakeLeaseOwnedSource(source_identity, [_tick(source_identity), None])
    bridge = _bridge(source)

    assert bridge.identity == source_identity
    assert bridge.poll_tick() == _tick(source_identity)
    assert bridge.poll_tick() is None
    assert source.lease_snapshot_reads >= 5
    assert source.poll_calls == 2

    bridge.retire()
    with pytest.raises(CtpSimNowManagedMdBridgeError, match="managed_md_bridge_closed"):
        bridge.poll_tick()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"md_front": "tcp://127.0.0.1:11999"}, "managed_md_source_scope_mismatch"),
        ({"account_fingerprint_sha256": "d" * 64}, "managed_md_source_scope_mismatch"),
        (
            {"instrument_id": "cu2701", "subscription_instrument_id": "cu2701"},
            "managed_md_source_scope_mismatch",
        ),
        ({"subscription_acknowledged": False}, "managed_md_source_not_ready"),
        ({"first_tick_observed": False}, "managed_md_source_not_ready"),
        ({"subscription_epoch": 0}, "managed_md_source_not_ready"),
        ({"connection_generation": 0}, "managed_md_source_not_ready"),
    ],
)
def test_bridge_rejects_wrong_or_unready_source_identity(changes, reason):
    source = _FakeLeaseOwnedSource(_identity(**changes))
    with pytest.raises(CtpSimNowManagedMdBridgeError) as rejected:
        _bridge(source)
    assert rejected.value.reason == reason
    assert source.poll_calls == 0


def test_bridge_requires_matching_native_readiness():
    selection, _ = _scope()
    wrong_readiness = CtpSimNowNativeReadiness(
        config_digest="d" * 64,
        registration_digest=_REGISTRATION,
        account_fingerprint_sha256=_ACCOUNT,
        md_front=_MD_FRONT,
        td_front=_TD_FRONT,
        td_ready=True,
        md_ready=True,
    )
    source = _FakeLeaseOwnedSource(_identity())
    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_readiness_scope_mismatch",
    ):
        CtpSimNowManagedMdTickBridge(selection, wrong_readiness, source)
    assert source.poll_calls == 0


def test_bridge_checks_lease_before_pinning_source_identity():
    source = _FakeLeaseOwnedSource(_identity())
    source.lease_active = False
    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_account_lease_lost",
    ):
        _bridge(source)
    assert source.lease_snapshot_reads == 1
    assert source.poll_calls == 0


def test_bridge_requires_identity_and_lease_snapshot_to_share_generation():
    source = _FakeLeaseOwnedSource(_identity())
    source.lease_generation = 8

    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_source_lease_generation_mismatch",
    ):
        _bridge(source)
    assert source.poll_calls == 0


@pytest.mark.parametrize(
    ("tick", "reason"),
    [
        (object(), "managed_md_tick_shape_unknown"),
        (_tick(sequence=100), "managed_md_tick_stale_or_out_of_order"),
        (
            _tick(identity=_identity(connection_generation=8)),
            "managed_md_tick_scope_or_generation_mismatch",
        ),
        (_tick(event_timestamp=1_799_999_998.0), "managed_md_tick_stale_or_out_of_order"),
        (_tick(received_monotonic_ns=9_000), "managed_md_tick_stale_or_out_of_order"),
        (_tick(instrument_id="cu2701"), "managed_md_tick_instrument_mismatch"),
        (_tick(stale=True, stale_reason="old generation"), "managed_md_tick_stale_or_out_of_order"),
        (_tick(last_price=float("nan")), "managed_md_tick_fields_invalid"),
        (_tick(bid_price=3502.0, ask_price=3501.0), "managed_md_tick_fields_invalid"),
    ],
)
def test_bridge_poisoned_by_unknown_stale_or_invalid_tick(tick, reason):
    source_identity = _identity()
    bridge = _bridge(_FakeLeaseOwnedSource(source_identity, [tick]))
    with pytest.raises(CtpSimNowManagedMdBridgeError) as rejected:
        bridge.poll_tick()
    assert rejected.value.reason == reason
    with pytest.raises(CtpSimNowManagedMdBridgeError) as poisoned:
        bridge.poll_tick()
    assert poisoned.value.reason == reason


def test_bridge_rejects_generation_change_and_lost_lease():
    source_identity = _identity()
    source = _FakeLeaseOwnedSource(source_identity, [_tick(source_identity)])
    bridge = _bridge(source)
    source.identity = _identity(connection_generation=8)

    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_source_generation_or_scope_changed",
    ):
        bridge.poll_tick()
    assert source.poll_calls == 0

    source = _FakeLeaseOwnedSource(source_identity, [_tick(source_identity)])
    bridge = _bridge(source)
    source.lease_active = False
    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_account_lease_lost",
    ):
        bridge.poll_tick()


def test_bridge_rechecks_scope_after_poll_before_exposing_tick():
    source_identity = _identity()
    source = _FakeLeaseOwnedSource(source_identity, [_tick(source_identity)])
    bridge = _bridge(source)

    def change_source_scope():
        source.identity = _identity(subscription_epoch=4)

    source.after_poll = change_source_scope

    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_source_generation_or_scope_changed",
    ):
        bridge.poll_tick()


def test_bridge_rejects_lease_loss_and_reacquisition_during_poll():
    source_identity = _identity()
    source = _FakeLeaseOwnedSource(source_identity, [_tick(source_identity)])
    bridge = _bridge(source)
    renewed_generation = 8

    def lose_and_reacquire_lease():
        source.lease_active = False
        source.lease_generation = renewed_generation
        source.identity = _identity(lease_generation=renewed_generation)
        source.lease_active = True

    source.after_poll = lose_and_reacquire_lease

    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_account_lease_changed",
    ):
        bridge.poll_tick()
    assert source.poll_calls == 1
    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_account_lease_changed",
    ):
        bridge.poll_tick()
    assert source.poll_calls == 1


def test_bridge_rejects_boolean_only_lease_source():
    selection, readiness = _scope()
    source = SimpleNamespace(
        identity=_identity(),
        assert_lease_active=lambda _account: True,
        poll_tick=lambda: pytest.fail("boolean-only source must not be polled"),
    )

    with pytest.raises(
        CtpSimNowManagedMdBridgeError,
        match="managed_md_lease_snapshot_unavailable",
    ):
        CtpSimNowManagedMdTickBridge(selection, readiness, source)
