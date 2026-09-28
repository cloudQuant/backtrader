"""Fake-only contracts for the unregistered 007 managed MD Feed candidate."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader.dataseries import TimeFrame
from backtrader_runtime.ctp_simnow_managed_md_bridge import (
    CtpSimNowManagedMdTickBridge,
    ManagedCtpMdLeaseSnapshot,
    ManagedCtpMdSourceIdentity,
    ManagedCtpMdTick,
)
from backtrader_runtime.ctp_simnow_managed_runtime import CtpSimNowNativeReadiness

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
INSTRUMENT = "rb2710"
EXCHANGE = "SHFE"
EVENT_TIME = 1_800_000_000.0


@pytest.fixture
def candidate_module():
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "common" or name.startswith("common.")
    }
    previous_path = sys.path[:]
    for name in previous_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(SUITE_ROOT))
    try:
        yield importlib.import_module("common.managed_md_feed_candidate")
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


def _identity():
    return ManagedCtpMdSourceIdentity(
        config_digest="a" * 64,
        registration_digest="b" * 64,
        account_fingerprint_sha256="c" * 64,
        lease_generation=7,
        md_front="tcp://127.0.0.1:11001",
        td_front="tcp://127.0.0.1:12001",
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        connection_generation=7,
        subscription_epoch=3,
        subscription_instrument_id=INSTRUMENT,
        subscription_acknowledged=True,
        first_tick_observed=True,
        ready_tick_sequence=100,
        ready_event_timestamp=EVENT_TIME - 1,
        ready_received_monotonic_ns=9_000,
    )


def _tick(identity=None, **overrides):
    values = {
        "identity": identity or _identity(),
        "sequence": 101,
        "event_timestamp": EVENT_TIME,
        "received_monotonic_ns": 10_000,
        "instrument_id": INSTRUMENT,
        "exchange_id": EXCHANGE,
        "last_price": 3500.0,
        "volume_delta": 2.0,
        "bid_price": 3499.0,
        "ask_price": 3501.0,
        "bid_volume": 4.0,
        "ask_volume": 5.0,
        "trading_day": "20260928",
        "action_day": "20260928",
        "update_time": "09:00:00",
        "update_millisec": 1,
        "stale": False,
        "stale_reason": "",
    }
    values.update(overrides)
    return ManagedCtpMdTick(**values)


class FakeLeaseOwnedSource:
    """Offline source with no provider, query, write, or native methods."""

    def __init__(self, identity, ticks=()):
        self.identity = identity
        self.ticks = list(ticks)
        self.lease_active = True
        self.lease_snapshot_reads = 0
        self.poll_calls = 0

    @property
    def lease_snapshot(self) -> ManagedCtpMdLeaseSnapshot:
        self.lease_snapshot_reads += 1
        return ManagedCtpMdLeaseSnapshot(
            account_fingerprint_sha256="c" * 64,
            lease_generation=self.identity.lease_generation,
            active=self.lease_active,
        )

    def poll_tick(self) -> Optional[ManagedCtpMdTick]:
        self.poll_calls += 1
        return self.ticks.pop(0) if self.ticks else None

    def start(self):  # pragma: no cover - bridge/feed must never start the source
        raise AssertionError("candidate must not start its owner source")


def _bridge(ticks=()):
    identity = _identity()
    registration = SimpleNamespace(
        digest="b" * 64,
        account_fingerprint_sha256="c" * 64,
        md_front="tcp://127.0.0.1:11001",
        td_front="tcp://127.0.0.1:12001",
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
    )
    selection = SimpleNamespace(
        execution_registration=registration,
        config_digest="a" * 64,
    )
    readiness = CtpSimNowNativeReadiness(
        config_digest="a" * 64,
        registration_digest="b" * 64,
        account_fingerprint_sha256="c" * 64,
        md_front=registration.md_front,
        td_front=registration.td_front,
        td_ready=True,
        md_ready=True,
    )
    source = FakeLeaseOwnedSource(identity, ticks)
    return CtpSimNowManagedMdTickBridge(selection, readiness, source), source


def _feed(module, bridge, **kwargs):
    return module.CtpSimNowManagedMdTickFeedCandidate(
        bridge=bridge,
        max_receive_age_ns=2_000,
        max_event_age_seconds=2.0,
        max_future_skew_seconds=0.0,
        **kwargs,
    )


def test_bridge_tick_advances_backtrader_tick_clock_and_strategy_lines(
    candidate_module, monkeypatch
):
    bridge, source = _bridge((_tick(),))
    monkeypatch.setattr(candidate_module, "_monotonic_ns", lambda: 10_500)
    monkeypatch.setattr(candidate_module, "_wall_time_seconds", lambda: EVENT_TIME + 0.25)
    feed = _feed(candidate_module, bridge)
    feed._start()

    assert feed.islive() is True
    assert feed.p.timeframe == TimeFrame.Ticks
    assert feed.load() is True
    assert feed.close[0] == 3500.0
    assert feed.open[0] == feed.high[0] == feed.low[0] == 3500.0
    assert feed.volume[0] == 2.0
    assert feed.bid[0] == 3499.0
    assert feed.ask[0] == 3501.0
    assert feed.bidvolume[0] == 4.0
    assert feed.askvolume[0] == 5.0
    assert feed.tick_sequence[0] == 101
    assert feed.connection_generation[0] == 7
    assert feed.openinterest[0] != feed.openinterest[0]  # NaN: unavailable in the envelope
    assert feed.num2date(feed.datetime[0]) == datetime.fromtimestamp(
        EVENT_TIME, timezone.utc
    ).replace(tzinfo=None)
    assert source.poll_calls == 1
    assert not hasattr(source, "submit_order_insert")
    assert not hasattr(source, "submit_order_action")
    feed.stop()


def test_idle_bridge_never_creates_a_seed_or_replay_bar(candidate_module, monkeypatch):
    bridge, source = _bridge()
    monkeypatch.setattr(candidate_module, "_monotonic_ns", lambda: 10_500)
    monkeypatch.setattr(candidate_module, "_wall_time_seconds", lambda: EVENT_TIME)
    feed = _feed(candidate_module, bridge, qcheck=0.0)
    feed._start()

    assert feed.load() is None
    assert len(feed) == 0
    assert source.poll_calls == 1
    feed.stop()


def test_candidate_bounds_idle_poll_wait_without_reading_a_tick(candidate_module):
    bridge, source = _bridge()

    with pytest.raises(candidate_module.CtpSimNowManagedMdFeedError, match="qcheck_out_of_bounds"):
        _feed(candidate_module, bridge, qcheck=1.01)

    assert source.poll_calls == 0


def test_lease_loss_disconnects_feed_before_source_poll_and_sticks(candidate_module, monkeypatch):
    bridge, source = _bridge((_tick(),))
    source.lease_active = False
    monkeypatch.setattr(candidate_module, "_monotonic_ns", lambda: 10_500)
    monkeypatch.setattr(candidate_module, "_wall_time_seconds", lambda: EVENT_TIME)
    feed = _feed(candidate_module, bridge)
    feed._start()

    with pytest.raises(candidate_module.CtpSimNowManagedMdFeedError, match="bridge_rejected"):
        feed.load()
    with pytest.raises(candidate_module.CtpSimNowManagedMdFeedError, match="bridge_rejected"):
        feed.load()
    assert source.poll_calls == 0
    assert feed.close[0] != 3500.0
    feed.stop()


@pytest.mark.parametrize(
    ("monotonic_now", "wall_now", "expected_reason"),
    [
        (12_001, EVENT_TIME + 0.25, "receive_expired"),
        (10_500, EVENT_TIME + 2.1, "event_expired_or_future"),
        (10_500, EVENT_TIME - 0.1, "event_expired_or_future"),
    ],
)
def test_stale_or_future_envelope_is_rejected_without_data_fallback(
    candidate_module, monkeypatch, monotonic_now, wall_now, expected_reason
):
    bridge, source = _bridge((_tick(),))
    monkeypatch.setattr(candidate_module, "_monotonic_ns", lambda: monotonic_now)
    monkeypatch.setattr(candidate_module, "_wall_time_seconds", lambda: wall_now)
    feed = _feed(candidate_module, bridge)
    feed._start()

    with pytest.raises(candidate_module.CtpSimNowManagedMdFeedError, match=expected_reason):
        feed.load()
    assert source.poll_calls == 1
    assert feed.close[0] != 3500.0
    with pytest.raises(candidate_module.CtpSimNowManagedMdFeedError):
        feed.load()
    assert source.poll_calls == 1
    feed.stop()


def test_candidate_stays_outside_default_33_runner_and_has_no_write_imports(candidate_module):
    source = Path(candidate_module.__file__).read_text(encoding="utf-8")
    assert "bt_api_ctp" not in source
    assert "backtrader.stores" not in source
    assert "backtrader.brokers" not in source
    case_runner_paths = sorted((SUITE_ROOT / "cases").glob("*/run.py"))
    assert len(case_runner_paths) == 33
    runner_paths = [
        SUITE_ROOT / "run_all.py",
        SUITE_ROOT / "run_case.py",
        *case_runner_paths,
    ]
    for path in runner_paths:
        assert "managed_md_feed_candidate" not in path.read_text(encoding="utf-8")
    assert "bt_api_ctp" not in sys.modules
