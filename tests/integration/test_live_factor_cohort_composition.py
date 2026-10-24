"""Production-feed composition checks for live factor cohort batches.

These cases use the real Cerebro, BtApiFeed, LiveBarCohort, LiveFactorSet,
BtApiStore and (for aggregated bars) BtApiFeed's production tick builder. Only
the provider-facing client is the repository's existing deterministic fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import FactorIndicator, FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortFrozenError,
    LiveCohortValidationError,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store, make_tick


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
_MISSING_CLOSE = object()
_FACTOR_ADVANCES: list[tuple[str, ...]] = []
_BAR_NOTIFICATIONS: list[tuple[str, str]] = []


class ReplayClock:
    """Small deterministic clock used by Cerebro's real cohort scheduler."""

    def __init__(self, now: datetime, *, advance_to: datetime | None = None):
        self.now = now
        self.advance_to = advance_to
        self.monotonic = 1_000
        self.waits: list[float] = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        elapsed = max(0.0, float(timeout_seconds))
        self.monotonic += max(1, int(elapsed * 1_000_000_000))
        if self.advance_to is not None and self.now < self.advance_to:
            self.now = min(self.advance_to, self.now + timedelta(seconds=elapsed))
        else:
            self.now += timedelta(seconds=elapsed)


class CohortClose(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("close")

    def next(self):
        _FACTOR_ADVANCES.append(tuple(data._name for data in self.datas))
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **_params):
        return ctx.close


class CohortStrategy(bt.Strategy):
    params = (("cohort", None), ("plan", None), ("raise_on_notify", False))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.batch_ids: list[str] = []
        self.snapshots = []
        self.notifications: list[tuple[str, str, str]] = []

    def notify_bar(self, bar):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        symbol = _event_value(bar, "symbol")
        data = next(data for data in self.datas if data._name == symbol)
        envelope = batch.receipt_for_feed(data).envelope
        # The callback is emitted from the completed envelope after every
        # member line has advanced, and names the exact published batch/bar.
        assert len({len(member) for member in self.datas}) == 1
        assert _event_value(bar, "bar_id") == envelope.bar_id
        assert _event_value(bar, "bucket_end") == envelope.close_time
        assert _event_value(bar, "available_at") == envelope.available_at
        self.notifications.append((symbol, envelope.bar_id, batch.batch_id))
        _BAR_NOTIFICATIONS.append((symbol, batch.batch_id))
        if self.p.raise_on_notify:
            raise RuntimeError("synthetic notify_bar callback failure")

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        assert len({len(data) for data in self.datas}) == 1
        assert all(
            data.datetime.datetime(0) == batch.close_time.replace(tzinfo=None)
            for data in self.datas
        )
        self.batch_ids.append(batch.batch_id)
        self.snapshots.append(self.live_factors.snapshot())


class Alpha003CohortStrategy(CohortStrategy):
    """Capture Alpha003's real cross-sectional rank before readiness gating."""

    def __init__(self):
        super().__init__()
        self.open_ranks = {}
        self.decision_batches = []
        self.batches = {}

    def prenext(self):
        # Strategy warmup callbacks still inspect the completed production
        # factor graph; this keeps early window/gap readiness observable.
        self.next()

    def next(self):
        super().next()
        batch = self.p.cohort.current_batch()
        self.batches[batch.close_time] = batch
        instance = self.live_factors.factor_instances["alpha003"]["portfolio"]
        rank_open = instance._nodes["rank_open"]
        self.open_ranks[batch.close_time] = {
            feed._name: rank_open.outputs[feed].value[0] for feed in self.datas
        }
        snapshot = self.snapshots[-1]
        if snapshot.readiness.value == "LIVE_READY":
            self.decision_batches.append(batch.batch_id)


class FiniteTickClient(FakeBtApiClient):
    """Existing fake provider client with an explicit replay EOF watermark."""

    def __init__(self, *, live_ticks, final_watermark, live_bars=None):
        super().__init__(live_ticks=live_ticks, live=live_bars)
        self.final_watermark = dict(final_watermark)
        self.last_polled_bar = None

    def poll_bar(self, dataname):
        self.last_polled_bar = super().poll_bar(dataname)
        return self.last_polled_bar

    def is_source_exhausted(self, symbol):
        return not self.live_ticks.get(symbol)

    def get_source_event_time_watermark(self, symbol):
        return self.final_watermark.get(symbol)


def _alpha003_run(*, slot_count: int, gap_index: int, source: str = "direct"):
    names = ("A", "B", "GAP")
    calendar, sessions = _calendar(names, slots=slot_count)
    cohort = LiveBarCohort(
        "cohort-alpha003-gap",
        calendar,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=120_000_000_000,
    )
    clock = ReplayClock(calendar.slots[0].close_time)
    bars_by_name = {}
    for asset_index, name in enumerate(names):
        session = sessions["member-" + name]
        events = []
        for bar_index, slot in enumerate(calendar.slots):
            close = 10.0 + asset_index + (bar_index * 0.1)
            open_value = float(1 + ((asset_index + bar_index) % 3))
            volume_value = float(1 + ((asset_index + 2 * bar_index) % 3))
            event = dict(
                _bar_event(
                    slot,
                    name,
                    bar_index + 1,
                    close,
                    trading_day=session.trading_day,
                    session_segment=session.session_segment,
                )
            )
            event["open"] = open_value
            event["high"] = max(open_value, close) + 1.0
            event["low"] = min(open_value, close) - 1.0
            event["volume"] = volume_value
            if bar_index == gap_index and name == "GAP":
                event.update(
                    {
                        "close": math.nan,
                        "present": False,
                        "quality": "MISSING",
                        "quality_flags": ("MISSING_FIELDS",),
                        "missing_fields": ("close",),
                    }
                )
            events.append(MappingProxyType(event))
        bars_by_name[name] = tuple(events)

    stores = {}
    if source == "store":
        # The fake API client deep-copies seeded bars on poll. Keep the raw
        # market values byte-for-byte equivalent while using the mutable input
        # shape expected by that established fake; BtApiStore's strict raw
        # mode returns a deep-copied mapping before cohort validation.
        store_bars = {
            name: tuple(dict(event) for event in events) for name, events in bars_by_name.items()
        }
        api = FiniteTickClient(live_ticks={}, final_watermark={}, live_bars=store_bars)
        store = make_store(api=api, provider="okx", preserve_raw_bars=True)
        stores = dict.fromkeys(names, store)
    elif source not in ("history", "direct"):
        raise ValueError("unsupported Alpha003 gap source")

    feeds = {}
    for name in names:
        member_bars = bars_by_name[name]
        feeds[name] = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=member_bars if source == "history" else (),
            live_bars=member_bars if source == "direct" else (),
            cohort_source_mode=True,
            store=stores.get(name),
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )

    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    for name in names:
        feed = feeds[name]
        cerebro.adddata(feed, name=name)
        cohort.register_member(
            "member-" + name,
            feed,
            instrument=name,
            source_ref="feed-" + name,
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )

    plan = LiveFactorPlan(
        targets=names,
        groups=dict.fromkeys(names, "portfolio"),
        factors={
            "alpha003": FactorSpec(
                name="alpha003",
                indicator=get_alpha(3),
                panel_line="factor",
                field_bindings={
                    "open": "feed:target:open",
                    "volume": "feed:target:volume",
                },
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=120_000_000_000,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(Alpha003CohortStrategy, cohort=cohort, plan=plan)
    return cerebro, cohort, feeds, clock, calendar


def _calendar(member_ids: tuple[str, ...], *, slots: int = 1):
    member_sessions = {
        f"member-{member_id}": LiveCalendarMemberSession(
            trading_day="2025-01-02" if index % 2 == 0 else "2025-01-03",
            session_segment="regular" if index % 2 == 0 else "night",
        )
        for index, member_id in enumerate(member_ids)
    }
    calendar_slots = tuple(
        LiveCalendarSlot(
            slot_id=f"slot-{index}",
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2025-01-02",
            session_segment="regular",
            member_sessions=member_sessions,
        )
        for index in range(slots)
    )
    calendar = LiveCohortCalendar(
        calendar_id="calendar-composition",
        version="v1",
        epoch_id=7,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics="session-v1",
        slots=calendar_slots,
    )
    return calendar, member_sessions


def _bar_event(
    slot: LiveCalendarSlot,
    symbol: str,
    sequence: int,
    close: float,
    *,
    available_at: datetime | None = None,
    trading_day: str,
    session_segment: str,
):
    try:
        valid_close = float(close)
    except (TypeError, ValueError, OverflowError):
        valid_close = 10.0
    if not math.isfinite(valid_close):
        valid_close = 10.0
    return MappingProxyType(
        {
            "instrument": symbol,
            "symbol": symbol,
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": available_at or slot.close_time,
            "trading_day": trading_day,
            "session_segment": session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "clock-replay",
            "connection_generation": "generation-1",
            "bar_sequence": sequence,
            "bar_id": f"{symbol}-bar-{sequence}",
            "open": valid_close - 0.5,
            "high": valid_close + 0.5,
            "low": valid_close - 1.0,
            "close": close,
            "volume": float(sequence),
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "cohort-composition-fixture",
        }
    )


def _event_value(event, name):
    if isinstance(event, dict):
        return event.get(name)
    return getattr(event, name)


def _tick_event(
    symbol: str,
    event_time: datetime,
    *,
    sequence: int,
    price: float,
    trading_day: str,
    session_segment: str,
):
    tick = make_tick(0, price, volume=2.0, symbol=symbol)
    tick.timestamp = event_time.timestamp()
    tick.local_time = event_time.timestamp()
    tick.datetime = event_time.replace(tzinfo=None)
    tick.clock_domain_id = "clock-replay"
    tick.connection_generation = "generation-1"
    tick.ingest_seq = sequence
    tick.sequence = sequence
    tick.event_id = f"{symbol}-tick-{sequence}"
    tick.schema_version = "backtrader.tick.v1"
    tick.volume_semantics = "delta"
    tick.delta_volume = 2.0
    tick.trading_day = trading_day
    tick.session_segment = session_segment
    tick.source = "finite-tick-client"
    return tick


def _compose_run(
    member_ids: tuple[str, ...],
    *,
    source_by_member: dict[str, str] | None = None,
    available_by_member: dict[str, datetime] | None = None,
    bad_close_by_member: dict[str, object] | None = None,
    missing_gap_members: tuple[str, ...] = (),
    missing_close_members: tuple[str, ...] = (),
    bad_session_member: str | None = None,
    missing_member: str | None = None,
    preserve_raw_store: bool = True,
    mode: str = "native",
    feed_order: tuple[str, ...] | None = None,
    reverse_registration: bool = False,
    raise_on_notify: bool = False,
):
    _FACTOR_ADVANCES.clear()
    _BAR_NOTIFICATIONS.clear()
    source_by_member = source_by_member or {}
    available_by_member = available_by_member or {}
    bad_close_by_member = bad_close_by_member or {}
    feed_order = feed_order or member_ids
    calendar, sessions = _calendar(member_ids)
    slot = calendar.slots[0]
    cohort = LiveBarCohort(
        "cohort-composition",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    delayed = max(available_by_member.values(), default=slot.close_time)
    clock = ReplayClock(slot.close_time, advance_to=delayed)

    tick_members = [name for name in member_ids if source_by_member.get(name) == "tick"]
    store_members = [name for name in member_ids if source_by_member.get(name) == "store"]
    stores = {}
    if tick_members or store_members:
        ticks_by_symbol = {}
        watermark_by_symbol = {}
        for name in tick_members:
            session = sessions[f"member-{name}"]
            ticks_by_symbol[name] = [
                _tick_event(
                    name,
                    slot.bucket_start + timedelta(seconds=5),
                    sequence=1,
                    price=20.0 + member_ids.index(name),
                    trading_day=session.trading_day,
                    session_segment=session.session_segment,
                )
            ]
            watermark_by_symbol[name] = available_by_member.get(name, slot.close_time)
        store_bars = {}
        for name in store_members:
            session = sessions[f"member-{name}"]
            close = bad_close_by_member.get(name, 10.0 + member_ids.index(name))
            raw = dict(
                _bar_event(
                    slot,
                    name,
                    1,
                    close,
                    available_at=available_by_member.get(name),
                    trading_day=session.trading_day,
                    session_segment=session.session_segment,
                )
            )
            # Keep normalized OHLC shape valid when a bad close is converted
            # to zero by the legacy tolerant Store path. The raw cohort path
            # must reject the original close type/value first.
            raw.update({"open": 1.0, "high": 100.0, "low": -1.0})
            if name in missing_gap_members:
                raw.update(
                    {
                        "present": False,
                        "quality": "MISSING",
                        "quality_flags": ("MISSING_FIELDS",),
                        "missing_fields": ("close",),
                    }
                )
            if name in missing_close_members:
                raw.pop("close")
            store_bars[name] = (raw,)
        client = FiniteTickClient(
            live_ticks=ticks_by_symbol,
            final_watermark=watermark_by_symbol,
            live_bars=store_bars,
        )
        store = make_store(
            api=client,
            provider="okx",
            preserve_raw_bars=preserve_raw_store,
        )
        stores = dict.fromkeys(tick_members + store_members, store)

    feeds_by_name = {}
    for name in member_ids:
        session = sessions[f"member-{name}"]
        source = source_by_member.get(name, "direct")
        close = float(10 + member_ids.index(name))
        if source == "tick":
            close = 20.0 + member_ids.index(name)
        if name in bad_close_by_member:
            close = bad_close_by_member[name]
        trading_day = session.trading_day
        session_segment = session.session_segment
        if name == bad_session_member:
            trading_day = "2099-12-31"
        event = _bar_event(
            slot,
            name,
            1,
            close,
            available_at=available_by_member.get(name),
            trading_day=trading_day,
            session_segment=session_segment,
        )
        if name in missing_gap_members:
            event = MappingProxyType(
                {
                    **dict(event),
                    "present": False,
                    "quality": "MISSING",
                    "quality_flags": ("MISSING_FIELDS",),
                    "missing_fields": ("close",),
                }
            )
        if name in missing_close_members:
            event = MappingProxyType(
                {field: value for field, value in event.items() if field != "close"}
            )
        source_kwargs = {
            "historical_bars": (event,) if source == "history" else (),
            "live_bars": (event,) if source == "direct" else (),
            "cohort_source_mode": True,
            "store": stores.get(name),
            "backfill_start": False,
            "timeframe": bt.TimeFrame.Minutes,
            "compression": 1,
            "bar_watermark_ms": 0,
            "clock": clock,
        }
        if name == missing_member:
            source_kwargs["historical_bars"] = ()
            source_kwargs["live_bars"] = ()
        feeds_by_name[name] = bt.feeds.BtApiFeed(dataname=name, **source_kwargs)

    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=3,
        preload=False,
        runonce=False,
    )
    for name in feed_order:
        cerebro.adddata(feeds_by_name[name], name=name)

    registration_order = tuple(reversed(member_ids)) if reverse_registration else member_ids
    for name in registration_order:
        cohort.register_member(
            f"member-{name}",
            feeds_by_name[name],
            instrument=name,
            source_ref=f"feed-{name}",
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    plan = LiveFactorPlan(
        targets=member_ids,
        groups=dict.fromkeys(member_ids, "portfolio"),
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
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        CohortStrategy,
        cohort=cohort,
        plan=plan,
        raise_on_notify=raise_on_notify,
    )
    return cerebro, cohort, feeds_by_name, clock, sessions, slot


@pytest.mark.integration
@pytest.mark.parametrize("member_count", (1, 2, 3, 5, 6, 20))
def test_real_cerebro_publishes_one_delayed_complete_batch_for_member_scales(member_count):
    names = tuple(f"S{index:02d}" for index in range(member_count))
    # Exercise different feed and registration orders while keeping the final
    # feed in scheduler order as the deliberately delayed last leg.
    reverse = member_count % 2 == 0
    feed_order = tuple(reversed(names)) if reverse else names
    registration_order_is_reversed = not reverse
    delayed_member = feed_order[-1]
    available_at = START + timedelta(minutes=1, seconds=2)
    cerebro, cohort, feeds, clock, sessions, slot = _compose_run(
        names,
        available_by_member={delayed_member: available_at},
        feed_order=feed_order,
        reverse_registration=registration_order_is_reversed,
    )

    strategy = cerebro.run()[0]

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert len(batch.members) == member_count
    assert len(strategy.batch_ids) == 1 and strategy.batch_ids[0] == batch.batch_id
    assert len(strategy.snapshots) == 1
    snapshot = strategy.snapshots[0]
    assert snapshot.batch_complete is True
    assert snapshot.close_time == slot.close_time
    assert snapshot.available_at == available_at
    assert clock.now >= available_at and clock.waits
    assert all(len(feed) == 1 for feed in feeds.values())
    assert all(feed.live_bar_cohort is cohort for feed in feeds.values())

    factor = snapshot.factors["close_value"]
    assert set(factor.values) == set(names)
    for index, name in enumerate(names):
        envelope = batch.receipt_for_feed(feeds[name]).envelope
        session = sessions[f"member-{name}"]
        assert envelope.source_role == "live"
        assert envelope.trading_day == session.trading_day
        assert envelope.session_segment == session.session_segment
        output = factor.values[name]
        assert output.value == pytest.approx(10.0 + index)
        assert output.source_ref == f"feed-{name}"
        assert output.sequence == 1

    assert len(strategy.notifications) == member_count
    assert all(item[2] == batch.batch_id for item in strategy.notifications)
    assert {item[0] for item in strategy.notifications} == set(names)
    assert [tuple(names)] == _FACTOR_ADVANCES
    assert len(_FACTOR_ADVANCES[0]) == member_count


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_history_tick_aggregate_and_store_direct_sources_compose_in_one_real_batch(mode):
    names = ("HISTORY", "TICK", "DIRECT")
    cerebro, cohort, feeds, clock, _sessions, slot = _compose_run(
        names,
        source_by_member={"HISTORY": "history", "TICK": "tick", "DIRECT": "store"},
        feed_order=("DIRECT", "HISTORY", "TICK"),
        reverse_registration=True,
        mode=mode,
    )

    strategy = cerebro.run()[0]

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert batch.close_time == slot.close_time
    assert batch.available_at == slot.close_time
    assert clock.now >= slot.close_time
    assert [len(feeds[name]) for name in names] == [1, 1, 1]
    outputs = strategy.snapshots[0].factors["close_value"].values
    expected = {"HISTORY": 10.0, "TICK": 21.0, "DIRECT": 12.0}
    for name in names:
        envelope = batch.receipt_for_feed(feeds[name]).envelope
        assert envelope.source_role == ("history" if name == "HISTORY" else "live")
        assert outputs[name].value == pytest.approx(expected[name])
        assert outputs[name].source_ref == f"feed-{name}"

    # The tick-produced event carries identity derived by the real feed bar
    # builder from its source generation/ingest sequence.
    tick_envelope = batch.receipt_for_feed(feeds["TICK"]).envelope
    assert tick_envelope.bar_id.startswith("TICK:")
    assert tick_envelope.feed_sequence == 1
    assert tick_envelope.available_at == slot.close_time
    direct_event = batch.receipt_for_feed(feeds["DIRECT"]).envelope.event_ref
    assert direct_event["source"] == "cohort-composition-fixture"
    assert direct_event["bucket_start"] == slot.bucket_start
    assert len(strategy.notifications) == 2
    assert {row[0] for row in strategy.notifications} == {"TICK", "DIRECT"}
    assert {row[2] for row in strategy.notifications} == {batch.batch_id}
    assert ([tuple(names)] if mode == "native" else []) == _FACTOR_ADVANCES


@pytest.mark.integration
def test_history_to_live_identical_bar_cutover_is_deduplicated_before_factor_advance():
    names = ("CUTOVER",)
    calendar, sessions = _calendar(names)
    slot = calendar.slots[0]
    event = _bar_event(
        slot,
        "CUTOVER",
        1,
        31.0,
        trading_day=sessions["member-CUTOVER"].trading_day,
        session_segment=sessions["member-CUTOVER"].session_segment,
    )
    duplicate = _bar_event(
        slot,
        "CUTOVER",
        2,
        31.0,
        trading_day=sessions["member-CUTOVER"].trading_day,
        session_segment=sessions["member-CUTOVER"].session_segment,
    )
    duplicate = MappingProxyType({**dict(duplicate), "volume": event["volume"]})
    feed = bt.feeds.BtApiFeed(
        dataname="CUTOVER",
        historical_bars=(event,),
        live_bars=(duplicate,),
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    _FACTOR_ADVANCES.clear()
    _BAR_NOTIFICATIONS.clear()
    cohort = LiveBarCohort("cohort-cutover", calendar, max_pending_slots=2, max_window_bars=4)
    cohort.register_member(
        "member-CUTOVER",
        feed,
        instrument="CUTOVER",
        source_ref="feed-CUTOVER",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    plan = LiveFactorPlan(
        targets=names,
        groups={"CUTOVER": "portfolio"},
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CohortClose,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=4,
    )
    clock = ReplayClock(slot.close_time)
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.adddata(feed, name="CUTOVER")
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(CohortStrategy, cohort=cohort, plan=plan)

    strategy = cerebro.run()[0]

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert len(feed) == 1
    assert feed.close[0] == 31.0
    assert batch.receipt_for_feed(feed).envelope.source_role == "history"
    assert batch.receipt_for_feed(feed).envelope.event_ref is event
    assert strategy.snapshots[0].factors["close_value"].values["CUTOVER"].source_role == "history"
    assert strategy.notifications == []
    assert _BAR_NOTIFICATIONS == []
    assert len(_FACTOR_ADVANCES) == 1


@pytest.mark.integration
@pytest.mark.parametrize("source", ("history", "direct"))
@pytest.mark.parametrize(
    "bad_close, expected_message",
    (("10.0", "supported numeric type"), (math.inf, "must be finite")),
)
def test_invalid_original_saved_raw_number_is_rejected_before_line_or_factor(
    source, bad_close, expected_message
):
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        ("BAD",),
        source_by_member={"BAD": source},
        bad_close_by_member={"BAD": bad_close},
    )
    feed = feeds["BAD"]
    raw_source = feed._cohort_history_source if source == "history" else feed._cohort_live_source
    assert raw_source[0]["close"] == bad_close

    with pytest.raises(LiveCohortValidationError, match=expected_message):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert len(feed) == 0
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
@pytest.mark.parametrize("source", ("history", "direct", "store"))
def test_declared_nan_missing_field_advances_real_feed_batch_with_gap_metadata(source):
    cerebro, cohort, feeds, _clock, calendar = _alpha003_run(
        slot_count=1,
        gap_index=0,
        source=source,
    )

    strategy = cerebro.run()[0]

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert batch.close_time == calendar.slots[0].close_time
    assert [len(feeds[name]) for name in ("A", "B", "GAP")] == [1, 1, 1]
    assert math.isnan(feeds["GAP"].close[0])
    assert math.isfinite(feeds["GAP"].open[0])
    receipt = batch.receipt_for_feed(feeds["GAP"])
    assert receipt.envelope.present is False
    assert receipt.envelope.quality == "MISSING"
    assert receipt.envelope.missing_fields == ("close",)
    assert receipt.envelope.quality_flags == ("MISSING_FIELDS",)
    assert math.isnan(receipt.raw_values["close"])
    snapshot = strategy.snapshots[0]
    assert snapshot.batch_complete is True
    assert snapshot.readiness.value == "WARMUP"
    assert "cohort_gap_present" in snapshot.readiness_reasons
    assert strategy.decision_batches == []
    ranks = strategy.open_ranks[batch.close_time]
    assert ranks["A"] == pytest.approx(0.5)
    assert ranks["B"] == pytest.approx(1.0)
    assert math.isnan(ranks["GAP"])
    output = snapshot.factors["alpha003"].values["GAP"]
    assert output.status.value == "OUTPUT_UNAVAILABLE"
    assert output.present is False
    assert output.quality == "MISSING"
    assert math.isnan(output.value)


@pytest.mark.integration
def test_alpha003_gap_excludes_member_from_rank_and_recovers_after_rolling_window():
    gap_index = 10
    recovery_index = gap_index + 10
    cerebro, cohort, feeds, _clock, calendar = _alpha003_run(
        slot_count=recovery_index + 2,
        gap_index=gap_index,
    )

    strategy = cerebro.run()[0]

    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"
    assert len(strategy.snapshots) == len(calendar.slots)
    gap_time = calendar.slots[gap_index].close_time
    gap_snapshot = strategy.snapshots[gap_index]
    gap_batch = strategy.batches[gap_time]
    gap_receipt = gap_batch.receipt_for_feed(feeds["GAP"])
    assert gap_snapshot.close_time == gap_time
    assert gap_snapshot.batch_complete is True
    assert gap_snapshot.readiness.value == "WARMUP"
    assert "cohort_gap_present" in gap_snapshot.readiness_reasons
    assert gap_receipt.present is False and gap_receipt.complete is True
    assert math.isfinite(feeds["GAP"].open[0])

    # Alpha003's production CrossSectionalRank sees only the two present
    # members: their ranks use a denominator of two, while the gap member is
    # excluded before ranking even though its open input is finite.
    gap_ranks = strategy.open_ranks[gap_time]
    assert gap_ranks["A"] == pytest.approx(0.5)
    assert gap_ranks["B"] == pytest.approx(1.0)
    assert math.isnan(gap_ranks["GAP"])
    assert gap_batch.batch_id not in strategy.decision_batches

    still_warm_time = calendar.slots[recovery_index - 1].close_time
    assert strategy.snapshots[recovery_index - 1].readiness.value == "WARMUP"
    assert (
        "input_window_incomplete_or_warmup_short"
        in strategy.snapshots[recovery_index - 1].readiness_reasons
    )
    assert still_warm_time > gap_time

    recovered = strategy.snapshots[recovery_index]
    recovery_time = calendar.slots[recovery_index].close_time
    recovery_batch = strategy.batches[recovery_time]
    assert recovered.close_time == recovery_time
    assert recovered.batch_complete is True
    assert recovered.readiness.value == "LIVE_READY"
    assert "cohort_gap_present" not in recovered.readiness_reasons
    assert recovery_batch.batch_id in strategy.decision_batches


@pytest.mark.integration
def test_unregistered_custom_factor_freezes_on_declared_missing_field_gap():
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        ("GAP",),
        bad_close_by_member={"GAP": math.nan},
        missing_gap_members=("GAP",),
    )

    with pytest.raises(LiveCohortFrozenError, match="unsupported_factor_gap_semantics"):
        cerebro.run()

    batch = cohort.current_batch()
    assert cohort.frozen is True
    assert cohort.frozen_reason == "unsupported_factor_gap_semantics"
    assert batch is not None and batch.status == "COMPLETE"
    assert len(feeds["GAP"]) == 1


@pytest.mark.integration
@pytest.mark.parametrize("source", ("history", "direct", "store"))
def test_missing_raw_close_is_not_repaired_before_cohort_capture(source):
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        ("MISSING",),
        source_by_member={"MISSING": source},
        missing_close_members=("MISSING",),
    )
    feed = feeds["MISSING"]

    with pytest.raises(LiveCohortValidationError, match="required raw field 'close' is missing"):
        cerebro.run()

    if source == "history":
        assert "close" not in feed._cohort_history_source[0]
    elif source == "direct":
        assert "close" not in feed._cohort_live_source[0]
    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert len(feed) == 0
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
def test_cohort_activation_rejects_a_store_that_normalizes_bars_before_capture():
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        ("STORE",),
        source_by_member={"STORE": "store"},
        preserve_raw_store=False,
    )
    feed = feeds["STORE"]
    store = feed.store

    with pytest.raises(ValueError, match="preserve_raw_bars=True"):
        cerebro.run()

    assert cohort.current_batch() is None
    assert feed.live_bar_cohort is None
    assert len(feed) == 0
    assert store._api.connected is False


@pytest.mark.integration
def test_wrong_member_session_metadata_fails_before_any_member_line_advances():
    names = ("A", "B", "C")
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        names,
        bad_session_member="C",
        feed_order=("B", "A", "C"),
    )

    with pytest.raises(LiveCohortValidationError, match="planned slot"):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(feeds[name]) for name in names] == [0, 0, 0]
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
def test_invalid_second_member_raw_value_does_not_advance_any_member_line():
    names = ("A", "B")
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        names,
        bad_close_by_member={"B": "not-a-number"},
    )

    with pytest.raises(LiveCohortValidationError, match="supported numeric type"):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(feeds[name]) for name in names] == [0, 0]
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
def test_delivery_failure_after_preflight_rolls_back_all_member_lines():
    names = ("A", "B")
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(names)
    original_load = feeds["B"]._load_live_bar_cohort_envelope

    def write_then_fail():
        assert original_load() is True
        raise OSError("synthetic second-member write failure")

    feeds["B"]._load_live_bar_cohort_envelope = write_then_fail

    with pytest.raises(OSError, match="second-member write failure"):
        cerebro.run()

    # Cohort delivery is a single engine transaction. A late member failure
    # must not leave any feed line or factor callback at a partial batch.
    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert [len(feeds[name]) for name in names] == [0, 0]
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
def test_notify_failure_freezes_but_preserves_already_published_complete_batch():
    names = ("A", "B")
    cerebro, cohort, feeds, _clock, _sessions, slot = _compose_run(
        names,
        raise_on_notify=True,
    )

    with pytest.raises(RuntimeError, match="synthetic notify_bar callback failure"):
        cerebro.run()

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert batch.close_time == slot.close_time
    assert len(batch.members) == len(names)
    assert [len(feeds[name]) for name in names] == [1, 1]
    assert [feeds[name].close[0] for name in names] == [10.0, 11.0]
    assert cohort.frozen is True
    assert cohort.frozen_reason == "engine_batch_delivery_failed"
    # The first callback observed a fully published batch, then raised. No
    # partial line rollback is allowed after user code has seen that batch.
    assert [("A", batch.batch_id)] == _BAR_NOTIFICATIONS
    assert _FACTOR_ADVANCES == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad_close, expected_message",
    (("not-numeric", "supported numeric type"), (math.inf, "must be finite")),
)
def test_btapi_store_preserves_raw_polled_bar_until_strict_cohort_capture(
    bad_close, expected_message
):
    cerebro, cohort, feeds, _clock, _sessions, _slot = _compose_run(
        ("STORE",),
        source_by_member={"STORE": "store"},
        bad_close_by_member={"STORE": bad_close},
    )
    feed = feeds["STORE"]
    captured = []
    capture_raw = feed._cohort_capture_source

    def record_then_capture(event, source_role, received_monotonic_ns, max_slot):
        if source_role == "live":
            captured.append(event["close"])
        return capture_raw(event, source_role, received_monotonic_ns, max_slot)

    feed._cohort_capture_source = record_then_capture

    with pytest.raises(LiveCohortValidationError, match=expected_message):
        cerebro.run()

    assert captured == [bad_close]
    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert len(feed) == 0
    assert _BAR_NOTIFICATIONS == []
    assert _FACTOR_ADVANCES == []
