"""R0 production-composition preflight for a bounded synthetic profile.

This complements the source-fake and registered Store contracts.  It proves
that one explicit finite fixture can pass through the real Cerebro/Feed/Cohort
path and that the listed unsupported configurations fail before a Store is
started.  It does not represent a real account, provider route, calendar, or
full instrument universe.
"""

from __future__ import annotations

import backtrader as bt
import pytest

from backtrader.research.live_cohort import LiveBarCohort
from tests.integration import test_live_factor_cohort_composition as composition


# Frozen parameters for this test fixture, not an operational readiness profile.
R0_SYNTHETIC_PROFILE = {
    "scope": "synthetic_two_member_fixture_not_full_pool",
    "route": "explicit_BtApiFeed_live_bars_tuple",
    "account": None,
    "targets": ("A", "B"),
    "groups": {"A": "portfolio", "B": "portfolio"},
    "factor_mode": "native",
    "field_bindings": {"close": "feed:target:close"},
    "member_line_fields": ("open", "high", "low", "close", "volume", "openinterest"),
    "raw_fields": ("open", "high", "low", "close", "volume", "openinterest"),
    "numeric_fields": ("open", "high", "low", "close", "volume", "openinterest"),
    "calendar_id": "calendar-composition",
    "calendar_version": "v1",
    "calendar_epoch": 7,
    "frequency": "1min",
    "timezone_id": "UTC",
    "clock_domain_id": "clock-replay",
    "runonce": False,
    "preload": False,
    "exactbars": 3,
    "warmup_min_bars": 1,
    "max_pending_slots": 2,
    "max_window_bars": 8,
    "wait_timeout_ns": 5_000_000_000,
    "max_live_bar_age_seconds": 60.0,
    "max_future_skew_seconds": 0.0,
    "allow_history_prewarm": True,
}


class _RecordingStore:
    """Observe Store startup without opening any provider or network route."""

    preserve_raw_bars = True

    def __init__(self):
        self.start_calls = 0

    def start(self, **_kwargs):
        self.start_calls += 1


class _NoopFilter:
    def __init__(self, _data):
        pass

    def __call__(self, _data):
        return False


def _attach_recording_store(cerebro, feeds):
    store = _RecordingStore()
    for feed in feeds:
        feed.store = store
        feed.p.store = store
    return store


def _unbound_synthetic_profile():
    targets = R0_SYNTHETIC_PROFILE["targets"]
    calendar, sessions = composition._calendar(targets)
    cohort = LiveBarCohort(
        "r0-invalid-clock",
        calendar,
        max_pending_slots=R0_SYNTHETIC_PROFILE["max_pending_slots"],
        max_window_bars=R0_SYNTHETIC_PROFILE["max_window_bars"],
        wait_timeout_ns=R0_SYNTHETIC_PROFILE["wait_timeout_ns"],
    )
    clock = composition.ReplayClock(calendar.slots[0].close_time)
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=R0_SYNTHETIC_PROFILE["exactbars"],
        preload=R0_SYNTHETIC_PROFILE["preload"],
        runonce=R0_SYNTHETIC_PROFILE["runonce"],
    )
    feeds = []
    for name in targets:
        session = sessions[f"member-{name}"]
        event = composition._bar_event(
            calendar.slots[0],
            name,
            1,
            10.0 + targets.index(name),
            trading_day=session.trading_day,
            session_segment=session.session_segment,
        )
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=(),
            live_bars=(event,),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=name)
        cohort.register_member(
            f"member-{name}",
            feed,
            instrument=name,
            source_ref=f"feed-{name}",
            line_fields=R0_SYNTHETIC_PROFILE["member_line_fields"],
            raw_fields=R0_SYNTHETIC_PROFILE["raw_fields"],
            numeric_fields=R0_SYNTHETIC_PROFILE["numeric_fields"],
        )
    return cerebro, cohort, feeds, clock


def _assert_profile_matches_composition(cerebro, cohort, feeds, strategy):
    profile = R0_SYNTHETIC_PROFILE
    calendar = cohort._calendar
    plan = strategy.p.plan
    factor = plan.factors["close_value"]

    assert profile["scope"] == "synthetic_two_member_fixture_not_full_pool"
    assert profile["route"] == "explicit_BtApiFeed_live_bars_tuple"
    assert profile["account"] is None
    assert tuple(plan.targets) == profile["targets"]
    assert dict(plan.groups) == profile["groups"]
    assert factor.mode == profile["factor_mode"]
    assert dict(factor.field_bindings) == profile["field_bindings"]
    assert calendar.calendar_id == profile["calendar_id"]
    assert calendar.version == profile["calendar_version"]
    assert calendar.epoch_id == profile["calendar_epoch"]
    assert calendar.frequency == profile["frequency"]
    assert calendar.timezone_id == profile["timezone_id"]
    assert calendar.clock_domain_id == profile["clock_domain_id"]
    assert plan.warmup_min_bars == profile["warmup_min_bars"]
    assert plan.max_live_bar_age_seconds == profile["max_live_bar_age_seconds"]
    assert plan.max_future_skew_seconds == profile["max_future_skew_seconds"]
    assert plan.allow_history_prewarm is profile["allow_history_prewarm"]
    assert cohort.max_pending_slots == plan.max_pending_slots == profile["max_pending_slots"]
    assert cohort.max_window_bars == plan.max_window_bars == profile["max_window_bars"]
    assert cohort.wait_timeout_ns == plan.wait_timeout_ns == profile["wait_timeout_ns"]
    assert cerebro.p.runonce == profile["runonce"]
    assert cerebro.p.preload == profile["preload"]
    assert cerebro.p.exactbars == profile["exactbars"]
    assert tuple(data._name for data in feeds) == profile["targets"]
    assert all(data.store is None for data in feeds)
    for data in feeds:
        member = cohort.member_for_feed(data)
        assert member is not None
        assert member.line_fields == profile["member_line_fields"]
        assert member.raw_fields == profile["raw_fields"]
        assert member.numeric_fields == profile["numeric_fields"]
        assert data.p.cohort_source_mode is True
        assert not data._cohort_history_source
        assert len(data._cohort_live_source) == 1


def test_valid_synthetic_profile_runs_through_real_cerebro_cohort_and_factor_path():
    cerebro, cohort, feeds, _clock, _sessions, slot = composition._compose_run(
        R0_SYNTHETIC_PROFILE["targets"], mode=R0_SYNTHETIC_PROFILE["factor_mode"]
    )

    strategy = cerebro.run()[0]

    _assert_profile_matches_composition(cerebro, cohort, feeds.values(), strategy)
    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert batch.close_time == slot.close_time
    assert len(strategy.batch_ids) == 1
    assert len(strategy.snapshots) == 1
    assert strategy.snapshots[0].batch_complete is True
    factor = strategy.snapshots[0].factors["close_value"]
    assert set(factor.values) == set(R0_SYNTHETIC_PROFILE["targets"])
    assert {name: value.value for name, value in factor.values.items()} == {
        "A": pytest.approx(10.0),
        "B": pytest.approx(11.0),
    }


@pytest.mark.parametrize(
    ("invalid_setup", "message"),
    (
        ("channel", "ordinary Cerebro feed mode"),
        ("oldsync", "oldsync or cheat_on_open"),
        ("cheat_on_open", "oldsync or cheat_on_open"),
        ("cheat_timer", "cheat timers"),
        ("filter", "feed filters"),
        ("extra_feed", "exactly cover the registered cohort members"),
    ),
)
def test_unsupported_profile_is_rejected_before_any_store_start(invalid_setup, message):
    cerebro, _cohort, feeds_by_name, clock, _sessions, _slot = composition._compose_run(
        R0_SYNTHETIC_PROFILE["targets"], mode=R0_SYNTHETIC_PROFILE["factor_mode"]
    )
    feeds = list(feeds_by_name.values())
    if invalid_setup == "filter":
        feeds[0].addfilter(_NoopFilter)
    elif invalid_setup == "extra_feed":
        extra = bt.feeds.BtApiFeed(
            dataname="EXTRA",
            historical_bars=(),
            live_bars=(),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
        )
        cerebro.adddata(extra, name="EXTRA")
        feeds.append(extra)
    elif invalid_setup == "cheat_timer":
        cerebro.add_timer(when=bt.Timer.SESSION_START, cheat=True)

    store = _attach_recording_store(cerebro, feeds)
    if invalid_setup == "channel":
        run = lambda: cerebro.run(channel=object())
    elif invalid_setup == "oldsync":
        run = lambda: cerebro.run(oldsync=True)
    elif invalid_setup == "cheat_on_open":
        run = lambda: cerebro.run(cheat_on_open=True)
    else:
        run = cerebro.run

    with pytest.raises(ValueError, match=message):
        run()

    assert store.start_calls == 0
    assert all(feed.live_bar_cohort is None for feed in feeds)


def test_invalid_clock_is_rejected_before_cohort_binding_and_store_start():
    cerebro, cohort, feeds, clock = _unbound_synthetic_profile()
    store = _attach_recording_store(cerebro, feeds)

    with pytest.raises(TypeError, match=r"utc_now\(\), monotonic_ns\(\), and wait"):
        cerebro.add_live_bar_cohort(cohort, clock=object())

    assert cerebro.live_bar_cohort is None
    assert not cohort._sealed
    assert store.start_calls == 0
    assert cerebro.add_live_bar_cohort(cohort, clock=clock) is cohort
    assert store.start_calls == 0
