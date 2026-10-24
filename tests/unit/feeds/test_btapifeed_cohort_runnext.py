"""Production-loop contracts for opt-in batch delivery through BtApiFeed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import FactorIndicator, FactorSpec, LiveFactorPlan, LiveFactorSet
import backtrader.research.live_cohort as live_cohort_module
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCapacityError,
    LiveCohortCalendar,
    LiveCohortValidationError,
)


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)


class FakeClock:
    """Explicit replay clock; it never reads process wall time."""

    def __init__(self, now, *, advance_to=None):
        self.now = now
        self.advance_to = advance_to
        self.monotonic = 1_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        self.monotonic += max(1, int(timeout_seconds * 1_000_000_000))
        if self.advance_to is not None and self.now < self.advance_to:
            self.now = self.advance_to
        else:
            self.now += timedelta(seconds=timeout_seconds)


class CohortClose(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("close")

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        return ctx.close


class CohortStrategy(bt.Strategy):
    params = (("cohort", None), ("plan", None))

    def __init__(self):
        assert all(data.live_bar_cohort is self.p.cohort for data in self.datas)
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.bar_notifications = []
        self.strategy_batches = []
        self.snapshots = []

    def notify_bar(self, bar):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        assert len(batch.members) == len(self.datas)
        # Every input line is already at this batch before the first callback.
        assert all(len(data) == len(self) + 1 for data in self.datas)
        self.bar_notifications.append((bar.symbol, batch.batch_id))

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        assert len(batch.members) == len(self.datas)
        assert len({len(data) for data in self.datas}) == 1
        assert all(
            data.datetime.datetime(0) == batch.close_time.replace(tzinfo=None)
            for data in self.datas
        )
        self.strategy_batches.append(batch.batch_id)
        self.snapshots.append(self.live_factors.snapshot())


def _event(slot, symbol, sequence, close, *, available_at=None):
    available_at = available_at or slot.close_time
    return {
        "instrument": symbol,
        "symbol": symbol,
        "timestamp": slot.close_time.timestamp(),
        "datetime": slot.close_time,
        "bucket_start": slot.bucket_start,
        "bucket_end": slot.close_time,
        "available_at": available_at,
        "trading_day": slot.trading_day,
        "session_segment": slot.session_segment,
        "timezone_id": "UTC",
        "clock_domain_id": "clock-replay",
        "connection_generation": "generation-1",
        "bar_sequence": sequence,
        "bar_id": "%s-%d" % (symbol, sequence),
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": float(sequence),
        "openinterest": 0.0,
        "present": True,
        "complete": True,
        "quality": "GOOD",
        "quality_flags": (),
        "source": "finite-replay",
    }


def _make_run(
    *,
    mode="native",
    include_b=True,
    b_available_at=None,
    bad_a_close=None,
    invalid_b_source=False,
):
    slot = LiveCalendarSlot(
        "slot-0",
        START,
        START + timedelta(minutes=1),
        "2025-01-02",
        "regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="calendar-replay",
        version="v1",
        epoch_id=7,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics="session-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort(
        "cohort-replay",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    close_time = slot.close_time
    event_a = _event(slot, "A", 1, 10.0)
    if bad_a_close is not None:
        event_a["close"] = bad_a_close
    event_b = _event(slot, "B", 1, 20.0, available_at=b_available_at)
    history_b = dict(event_b) if invalid_b_source else MappingProxyType(dict(event_b))
    feeds = (
        bt.feeds.BtApiFeed(
            dataname="A",
            historical_bars=(MappingProxyType(dict(event_a)),),
            live_bars=(),
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        ),
        bt.feeds.BtApiFeed(
            dataname="B",
            historical_bars=(history_b,) if include_b else (),
            live_bars=(),
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        ),
    )
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    for name, feed in zip(("A", "B"), feeds):
        cerebro.adddata(feed, name=name)
        cohort.register_member(
            "member-" + name,
            feed,
            instrument=name,
            source_ref="source-" + name,
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    plan = LiveFactorPlan(
        targets=("A", "B"),
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CohortClose,
                panel_line="factor",
                mode=mode,
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    clock = FakeClock(
        close_time,
        advance_to=b_available_at,
    )
    cerebro.addstrategy(CohortStrategy, cohort=cohort, plan=plan)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    return cerebro, cohort, feeds, clock


def test_finite_calendar_capacity_includes_warmup_before_a_100k_evaluation_window(
    monkeypatch,
):
    assert live_cohort_module._MAX_CALENDAR_SLOTS == 200_000
    slot_count = 100_030
    slots = tuple(
        LiveCalendarSlot(
            "slot-%d" % index,
            START + timedelta(minutes=index),
            START + timedelta(minutes=index + 1),
            "2025-01-02",
            "regular",
        )
        for index in range(slot_count)
    )

    calendar = LiveCohortCalendar(
        calendar_id="calendar-long-finite",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics="session-v1",
        slots=slots,
    )

    assert len(calendar.slots) == slot_count

    over_limit = tuple(
        LiveCalendarSlot(
            "small-%d" % index,
            START + timedelta(minutes=index),
            START + timedelta(minutes=index + 1),
            "2025-01-02",
            "regular",
        )
        for index in range(4)
    )
    monkeypatch.setattr(live_cohort_module, "_MAX_CALENDAR_SLOTS", 3)
    with pytest.raises(LiveCohortCapacityError, match="finite slot limit"):
        LiveCohortCalendar(
            calendar_id="calendar-over-limit",
            version="v1",
            epoch_id=1,
            frequency="1min",
            frequency_seconds=60,
            timezone_id="UTC",
            clock_domain_id="clock-replay",
            session_semantics="session-v1",
            slots=over_limit,
        )


@pytest.mark.parametrize("mode", ("native", "build"))
def test_real_runnext_publishes_complete_history_batch_before_strategy_and_factors(mode):
    available_at = START + timedelta(minutes=1, seconds=2)
    cerebro, cohort, feeds, clock = _make_run(mode=mode, b_available_at=available_at)

    strategy = cerebro.run()[0]

    assert len(clock.waits) == 1
    assert all(value <= 0.05 for value in clock.waits)
    assert [len(data) for data in feeds] == [1, 1]
    assert [data.datetime.datetime(0) for data in feeds] == [
        (START + timedelta(minutes=1)).replace(tzinfo=None),
        (START + timedelta(minutes=1)).replace(tzinfo=None),
    ]
    assert strategy.bar_notifications == []
    assert len(strategy.strategy_batches) == 1
    assert len(strategy.snapshots) == 1
    snapshot = strategy.snapshots[0]
    assert snapshot.batch_complete is True
    assert snapshot.readiness.value == "WARMUP"
    assert snapshot.available_at == available_at
    assert snapshot.factors["close_value"].values["A"].value == 10.0
    assert snapshot.factors["close_value"].values["B"].value == 20.0
    assert snapshot.factors["close_value"].values["A"].source_role == "history"
    assert snapshot.factors["close_value"].values["B"].source_role == "history"
    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert all(batch.receipt_for_feed(feed).envelope.feed_ref is feed for feed in feeds)


def test_finite_eof_with_missing_member_freezes_without_partial_callback_or_line():
    cerebro, cohort, feeds, clock = _make_run(include_b=False)

    strategy = cerebro.run()[0]

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(data) for data in feeds] == [0, 0]
    assert strategy.bar_notifications == []
    assert strategy.strategy_batches == []
    assert strategy.snapshots == []
    assert clock.waits == []


def test_invalid_original_raw_number_is_rejected_before_any_feed_line_or_callback():
    cerebro, cohort, feeds, _clock = _make_run(bad_a_close="10.0")

    with pytest.raises(LiveCohortValidationError, match="supported numeric type"):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(data) for data in feeds] == [0, 0]


def test_failure_during_second_normal_feed_load_never_reaches_notify_bar_or_next():
    cerebro, cohort, feeds, _clock = _make_run()
    feeds[1]._load_live_bar_cohort_envelope = lambda: (_ for _ in ()).throw(
        OSError("synthetic second-member line failure")
    )

    with pytest.raises(OSError, match="second-member line failure"):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(data) for data in feeds] == [1, 1]
    assert feeds[0].close[0] == 10.0
    assert feeds[1].close[0] != 20.0


@pytest.mark.parametrize(
    "run_kwargs, message",
    (
        ({"runonce": False}, "preload=False"),
        ({"preload": False}, "runonce=False"),
        ({"preload": False, "runonce": False, "oldsync": True}, "oldsync"),
    ),
)
def test_unsupported_run_flags_fail_before_feed_start(run_kwargs, message):
    class RecordingStore:
        started = False

        def start(self, **_kwargs):
            self.started = True

        def register(self, _feed):
            pass

        def subscribe(self, _symbol):
            pass

    store = RecordingStore()
    cerebro, _cohort, feeds, _clock = _make_run()
    if run_kwargs.get("runonce") is False and "preload" not in run_kwargs:
        cerebro.p.preload = True
    if run_kwargs.get("preload") is False and "runonce" not in run_kwargs:
        cerebro.p.runonce = True
    for feed in feeds:
        feed.store = store
        feed.p.store = store

    with pytest.raises(ValueError, match=message):
        cerebro.run(**run_kwargs)

    assert store.started is False


def test_cohort_activation_validates_all_sources_before_mutation_and_can_retry():
    cerebro, cohort, feeds, _clock = _make_run(invalid_b_source=True)
    before = tuple(
        (
            feed.live_bar_cohort,
            feed._cohort_clock,
            feed._cohort_history_iter,
            feed._cohort_live_iter,
            feed._cohort_slot_index_by_close,
            feed._history,
            tuple(feed._history),
            feed._live,
            tuple(feed._live),
        )
        for feed in feeds
    )

    with pytest.raises(ValueError, match="immutable MappingProxyType"):
        cerebro.run()

    assert cohort.current_batch() is None
    for feed, prior in zip(feeds, before):
        assert feed.live_bar_cohort is prior[0] is None
        assert feed._cohort_clock is prior[1] is None
        assert feed._cohort_history_iter is prior[2] is None
        assert feed._cohort_live_iter is prior[3] is None
        assert feed._cohort_slot_index_by_close is prior[4]
        assert feed._history is prior[5]
        assert tuple(feed._history) == prior[6]
        assert feed._live is prior[7]
        assert tuple(feed._live) == prior[8]

    # Correct the exact second-feed source and retry the same Cerebro object.
    # The first attempt must not have consumed either normalized legacy queue.
    invalid_event = feeds[1]._cohort_history_source[0]
    feeds[1]._cohort_history_source = (MappingProxyType(dict(invalid_event)),)
    strategy = cerebro.run()[0]

    assert all(feed.live_bar_cohort is cohort for feed in feeds)
    assert [len(feed) for feed in feeds] == [1, 1]
    assert [feed.close[0] for feed in feeds] == [10.0, 20.0]
    assert len(strategy.strategy_batches) == 1
    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"


def test_channel_mode_fails_before_starting_the_cohort():
    class RecordingStore:
        started = False

        def start(self, **_kwargs):
            self.started = True

        def register(self, _feed):
            pass

        def subscribe(self, _symbol):
            pass

    store = RecordingStore()
    cerebro, _cohort, feeds, _clock = _make_run()
    for feed in feeds:
        feed.store = store
        feed.p.store = store

    with pytest.raises(ValueError, match="ordinary Cerebro feed mode"):
        cerebro.run(channel=True)

    assert store.started is False
