"""Compose the public futures-minute planner with the real live cohort path.

The exchange schedules and source events are deterministic fixture leaves.
Planner, cohort, exact BtApiFeed objects, Alpha003 and Cerebro remain production
objects.  This covers the calendar-break, planned-gap rebuild and explicit
quality-gap boundary without repeating the independent formula matrix.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType

import backtrader as bt
import pandas as pd
import pytest

from backtrader.feeds.futures_main_contract import ProductKey
from backtrader.feeds.futures_sessions import (
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionWindow,
    build_common_minute_grid,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from tests.integration import test_live_alpha003_cohort_scenarios as scenarios
from tests.integration import test_live_alpha003_parity as parity


_UTC = timezone.utc
_CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
_TRADING_DAY = date(2026, 10, 22)
_PRODUCTS = (
    ProductKey("SHFE", "CU"),
    ProductKey("DCE", "M"),
    ProductKey("CFFEX", "IF"),
)
_ASSETS = tuple("%s.%s" % (product.exchange_id, product.product_id) for product in _PRODUCTS)
_FIELDS = parity._OHLCV_FIELDS
_GAP_INDEX = 34
_RECOVERY_OFFSET = 10


class _CalendarReplayClock:
    """Advance only when ordinary Cerebro requests an injected-clock wait."""

    def __init__(self, now: datetime):
        self.now = now
        self._monotonic_ns = 1_000_000_000
        self.wait_records = []
        self._observe = None

    def bind_observer(self, callback):
        self._observe = callback

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self._monotonic_ns

    def wait(self, timeout_seconds):
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise AssertionError("Cerebro requested an invalid calendar wait")
        before = self._observe() if self._observe is not None else None
        self.wait_records.append({"timeout_seconds": timeout, "before": before})
        self._monotonic_ns += max(1, int(timeout * 1_000_000_000))
        if timeout:
            self.now += timedelta(seconds=timeout)
        after = self._observe() if self._observe is not None else None
        self.wait_records[-1]["after"] = after


class _CalendarCapture(parity._LiveAlpha003Capture):
    """Record actual strategy callbacks and complete cohort receipts."""

    params = (("clock", None),)

    def __init__(self):
        super().__init__()
        self.line_lengths = []
        self.batches = []

    def _capture(self):
        super()._capture()
        batch = self.p.cohort.current_batch()
        self.batches.append(batch)
        self.line_lengths.append(tuple(len(data) for data in self.datas))


def _local_time(hour: int, minute: int) -> datetime:
    return datetime.combine(_TRADING_DAY, time(hour, minute), tzinfo=_CHINA)


def _planner_grid():
    """Build a finite 50-close, full-group schedule with a real lunch break."""
    source_available = datetime(2026, 10, 20, 0, tzinfo=_UTC)
    source_retrieved = source_available + timedelta(hours=1)
    calendars = []
    for product in _PRODUCTS:
        exchange = product.exchange_id
        calendar_source = "%s.fixture.calendar" % exchange
        session_source = "%s.fixture.sessions" % exchange
        sources = tuple(
            PublicSourceEvidence(
                source_id=source_id,
                source_url="https://fixture.invalid/%s" % source_id,
                version="fixture-v1",
                available_at=source_available,
                retrieved_at=source_retrieved,
                sha256=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            )
            for source_id in (calendar_source, session_source)
        )
        windows = (
            SessionWindow(
                session_id="morning",
                session_date=_TRADING_DAY,
                start=_local_time(9, 30),
                end=_local_time(10, 0),
                source_id=session_source,
            ),
            SessionWindow(
                session_id="afternoon",
                session_date=_TRADING_DAY,
                start=_local_time(13, 30),
                end=_local_time(13, 50),
                source_id=session_source,
            ),
        )
        calendars.append(
            ExchangeSessionCalendar(
                exchange_id=exchange,
                calendar_source_id=calendar_source,
                coverage_start=_TRADING_DAY,
                coverage_through=_TRADING_DAY,
                trading_days=(_TRADING_DAY,),
                product_universe=(product,),
                product_days=(
                    ProductTradingDaySessions(
                        product=product,
                        trading_day=_TRADING_DAY,
                        source_id=session_source,
                        windows=windows,
                    ),
                ),
                sources=sources,
            )
        )
    grid = build_common_minute_grid(
        _PRODUCTS,
        tuple(calendars),
        dict.fromkeys(_PRODUCTS, (_TRADING_DAY,)),
        decision_at=datetime(2026, 10, 23, 0, tzinfo=_UTC),
    )
    assert grid.status == "READY"
    assert grid.target_products == _PRODUCTS
    assert len(grid.minutes) == 50
    closes = tuple(point.close_time for point in grid.minutes)
    assert closes[0] == datetime(2026, 10, 22, 1, 31, tzinfo=_UTC)
    assert closes[29] == datetime(2026, 10, 22, 2, 0, tzinfo=_UTC)
    assert closes[30] == datetime(2026, 10, 22, 5, 31, tzinfo=_UTC)
    assert closes[-1] == datetime(2026, 10, 22, 5, 50, tzinfo=_UTC)
    assert closes[30] - closes[29] == timedelta(hours=3, minutes=31)
    assert all(
        closes[index] - closes[index - 1] == timedelta(minutes=1)
        for index in tuple(range(1, 30)) + tuple(range(31, 50))
    )
    return grid


def _live_calendar(grid, epoch_id):
    member_ids = {asset: "member:%s" % asset for asset in _ASSETS}
    slots = []
    for slot_index, planned in enumerate(grid.minutes):
        sessions = {
            member_ids[asset]: LiveCalendarMemberSession(
                trading_day=evidence.trading_day.strftime("%Y%m%d"),
                session_segment=evidence.session_id,
            )
            for asset, evidence in zip(_ASSETS, planned.members)
        }
        session_segment = planned.members[0].session_id
        trading_day = planned.members[0].trading_day.strftime("%Y%m%d")
        slots.append(
            LiveCalendarSlot(
                slot_id="planner-slot-%03d" % slot_index,
                bucket_start=planned.close_time - timedelta(minutes=1),
                close_time=planned.close_time,
                trading_day=trading_day,
                session_segment=session_segment,
                member_sessions=MappingProxyType(sessions),
            )
        )
    calendar = LiveCohortCalendar(
        calendar_id="alpha003-futures-common-minute-v1",
        version="fixture-calendar-v1",
        epoch_id=epoch_id,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="alpha003-futures-calendar-replay-v1",
        session_semantics="explicit-futures-member-session-v1",
        slots=tuple(slots),
    )
    return calendar, member_ids


def _frames(grid):
    source = scenarios._scenario_frames(3)
    planner_index = pd.DatetimeIndex([point.close_time for point in grid.minutes])
    result = {}
    for asset, fixture_asset in zip(_ASSETS, source):
        frame = source[fixture_asset].iloc[: len(grid.minutes)].copy(deep=True)
        frame.index = planner_index
        result[asset] = frame
    return result


def _events(grid, frames, *, omitted_asset=None, omitted_index=None, gap_asset=None):
    product_index = {asset: index for index, asset in enumerate(_ASSETS)}
    result = {}
    for asset in _ASSETS:
        raw_events = parity._bar_events({asset: frames[asset]}, asset)
        rows = []
        for slot_index, event in enumerate(raw_events):
            if asset == omitted_asset and slot_index == omitted_index:
                continue
            payload = dict(event)
            evidence = grid.minutes[slot_index].members[product_index[asset]]
            payload["trading_day"] = evidence.trading_day.strftime("%Y%m%d")
            payload["session_segment"] = evidence.session_id
            payload["clock_domain_id"] = "alpha003-futures-calendar-replay-v1"
            if asset == gap_asset and slot_index == _GAP_INDEX:
                payload.update(
                    {
                        "close": math.nan,
                        "present": False,
                        "quality": "MISSING",
                        "quality_flags": ("MISSING_FIELDS",),
                        "missing_fields": ("close",),
                    }
                )
            rows.append(MappingProxyType(payload))
        result[asset] = tuple(rows)
    return result


def _run_calendar_stream(grid, frames, *, epoch_id, mode, omitted_asset=None, gap_asset=None):
    calendar, member_ids = _live_calendar(grid, epoch_id)
    cohort = LiveBarCohort(
        "alpha003-futures-epoch-%d-%s" % (epoch_id, mode),
        calendar,
        max_pending_slots=1,
        max_window_bars=len(grid.minutes),
        wait_timeout_ns=2_000_000,
    )
    clock = _CalendarReplayClock(grid.minutes[0].close_time)
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    events = _events(
        grid,
        frames,
        omitted_asset=omitted_asset,
        omitted_index=_GAP_INDEX if omitted_asset is not None else None,
        gap_asset=gap_asset,
    )
    for asset in _ASSETS:
        feed = bt.feeds.BtApiFeed(
            dataname=asset,
            historical_bars=(),
            live_bars=events[asset],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)
    for asset in _ASSETS:
        cohort.register_member(
            member_ids[asset],
            feeds[asset],
            instrument=asset,
            source_ref="futures-calendar-fixture:%s" % asset,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )
    plan = parity._live_alpha003_plan(
        _ASSETS,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=cohort.max_window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=5.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _CalendarCapture,
        cohort=cohort,
        plan=plan,
        target_order=_ASSETS,
        clock=clock,
    )
    clock.bind_observer(
        lambda: (
            tuple(len(feed) for feed in feeds.values()),
            None if cohort.current_batch() is None else cohort.current_batch().slot_index,
        )
    )
    strategy = cerebro.run()[0]
    return strategy, cohort, feeds, clock, calendar


def _assert_same_value(left, right, context):
    left, right = float(left), float(right)
    if math.isnan(left):
        assert math.isnan(right), context
    else:
        assert left == right, (context, left, right)


def _assert_recovered_suffix_matches(reference, rebuilt, start):
    assert len(reference.snapshots) == len(rebuilt.snapshots) == 50
    for row_index in range(start, 50):
        left = reference.snapshots[row_index]
        right = rebuilt.snapshots[row_index]
        assert left.close_time == right.close_time
        for asset in _ASSETS:
            left_output = left.factors["alpha003"].values[asset]
            right_output = right.factors["alpha003"].values[asset]
            assert (
                left_output.status,
                left_output.reason,
                left_output.present,
                left_output.quality,
            ) == (
                right_output.status,
                right_output.reason,
                right_output.present,
                right_output.quality,
            ), (
                row_index,
                asset,
            )
            _assert_same_value(left_output.value, right_output.value, (row_index, asset))

    left_factor = parity._factor_for_live(reference)
    right_factor = parity._factor_for_live(rebuilt)
    left_values, left_reasons = scenarios._node_values_and_reasons(left_factor, _ASSETS, 50)
    right_values, right_reasons = scenarios._node_values_and_reasons(right_factor, _ASSETS, 50)
    assert set(left_values) == set(right_values)
    for node_name in left_values:
        if node_name.startswith("rank_"):
            for asset_index, asset in enumerate(_ASSETS):
                for row_index in range(start, 50):
                    _assert_same_value(
                        left_values[node_name][asset_index][row_index],
                        right_values[node_name][asset_index][row_index],
                        (node_name, asset, row_index),
                    )
                assert (
                    left_reasons[node_name][asset_index][start:]
                    == right_reasons[node_name][asset_index][start:]
                ), (node_name, asset)
        else:
            for row_index in range(start, 50):
                _assert_same_value(
                    left_values[node_name][row_index],
                    right_values[node_name][row_index],
                    (node_name, row_index),
                )
            assert left_reasons[node_name][start:] == right_reasons[node_name][start:]


def _assert_complete_run(strategy, cohort, feeds, grid, clock):
    assert not cohort.frozen
    assert cohort.epoch_id == cohort._calendar.epoch_id
    assert len(strategy.snapshots) == len(grid.minutes) == 50
    assert len(strategy.factor_callback_times) == 50
    assert strategy.factor_callback_times == [point.close_time for point in grid.minutes]
    assert strategy.line_lengths == [tuple([row + 1] * 3) for row in range(50)]
    assert [batch.slot_index for batch in strategy.batches] == list(range(50))
    assert all(batch.status == "COMPLETE" and len(batch.members) == 3 for batch in strategy.batches)
    assert all(len(feed) == 50 for feed in feeds.values())

    long_break = (grid.minutes[30].close_time - grid.minutes[29].close_time).total_seconds()
    idle_records = [record for record in clock.wait_records if record["timeout_seconds"] > 60.0]
    assert len(idle_records) == 1
    lunch_wait = idle_records[0]
    assert lunch_wait["timeout_seconds"] == pytest.approx(long_break)
    assert lunch_wait["before"] == ((30, 30, 30), 29)
    assert lunch_wait["after"] == lunch_wait["before"]
    assert len(clock.wait_records) <= 50
    assert all(record["timeout_seconds"] > 0 for record in clock.wait_records)

    first_read = cohort.next_wait_timeout(clock.utc_now(), clock.monotonic_ns())
    before_query = (
        tuple(len(feed) for feed in feeds.values()),
        len(strategy.snapshots),
        cohort.current_batch(),
        cohort.gaps,
    )
    second_read = cohort.next_wait_timeout(clock.utc_now(), clock.monotonic_ns())
    after_query = (
        tuple(len(feed) for feed in feeds.values()),
        len(strategy.snapshots),
        cohort.current_batch(),
        cohort.gaps,
    )
    assert first_read.status == second_read.status == "EXHAUSTED"
    assert first_read.reason == second_read.reason == "finite_calendar_exhausted"
    assert first_read.timeout_seconds is second_read.timeout_seconds is None
    assert before_query == after_query


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_planner_calendar_break_gap_rebuild_and_alpha003_continuation(mode):
    """Exercise the planned lunch break, freeze/rebuild boundary and explicit gap."""
    planned = _planner_grid()
    frames = _frames(planned)

    # A source omission at a planned common minute freezes the old finite epoch
    # before any member line or Alpha003 callback can advance for that slot.
    missing_asset = _ASSETS[-1]
    frozen, old_cohort, old_feeds, old_clock, old_calendar = _run_calendar_stream(
        planned,
        frames,
        epoch_id=1,
        mode=mode,
        omitted_asset=missing_asset,
    )
    assert old_calendar.epoch_id == old_cohort.epoch_id == 1
    assert old_cohort.frozen and old_cohort.frozen_reason == "planned_gap_requires_rebuild"
    assert len(old_cohort.gaps) == 1
    assert old_cohort.gaps[0].slot_index == _GAP_INDEX
    assert old_cohort.gaps[0].close_time == planned.minutes[_GAP_INDEX].close_time
    assert old_cohort.gaps[0].missing_member_ids == ("member:%s" % missing_asset,)
    assert len(frozen.snapshots) == _GAP_INDEX
    assert frozen.factor_callback_times == [
        point.close_time for point in planned.minutes[:_GAP_INDEX]
    ]
    assert frozen.line_lengths == [tuple([row + 1] * 3) for row in range(_GAP_INDEX)]
    assert all(len(feed) == _GAP_INDEX for feed in old_feeds.values())
    assert [batch.slot_index for batch in frozen.batches] == list(range(_GAP_INDEX))
    assert all(batch.status == "COMPLETE" for batch in frozen.batches)
    assert len(old_clock.wait_records) <= _GAP_INDEX + 1
    gap_waits = [record for record in old_clock.wait_records if record["timeout_seconds"] < 0.01]
    assert len(gap_waits) == 1
    assert gap_waits[0]["before"] == ((_GAP_INDEX,) * 3, _GAP_INDEX - 1)
    assert gap_waits[0]["after"] == gap_waits[0]["before"]
    assert old_cohort._next_slot_index == _GAP_INDEX
    frozen_before_query = (
        len(frozen.snapshots),
        tuple(len(feed) for feed in old_feeds.values()),
        old_cohort.current_batch(),
        old_cohort.gaps,
        old_cohort._next_slot_index,
    )
    frozen_read = old_cohort.next_wait_timeout(old_clock.utc_now(), old_clock.monotonic_ns())
    frozen_after_query = (
        len(frozen.snapshots),
        tuple(len(feed) for feed in old_feeds.values()),
        old_cohort.current_batch(),
        old_cohort.gaps,
        old_cohort._next_slot_index,
    )
    assert frozen_read.status == "FROZEN"
    assert frozen_read.reason == "planned_gap_requires_rebuild"
    assert frozen_before_query == frozen_after_query

    # The new epoch restores the missing planned slot. Its explicit MISSING
    # receipt remains in place, so Alpha003's accepted 09b semantics can mask
    # it and recover after the rolling window passes it without compressing.
    rebuilt, new_cohort, new_feeds, new_clock, new_calendar = _run_calendar_stream(
        planned,
        frames,
        epoch_id=2,
        mode=mode,
        gap_asset=missing_asset,
    )
    (
        baseline,
        baseline_cohort,
        baseline_feeds,
        baseline_clock,
        baseline_calendar,
    ) = _run_calendar_stream(
        planned,
        frames,
        epoch_id=2,
        mode=mode,
        gap_asset=missing_asset,
    )
    assert old_cohort.frozen and old_cohort.epoch_id == 1
    assert new_calendar.epoch_id == new_cohort.epoch_id == 2
    assert new_cohort.cohort_id != old_cohort.cohort_id
    assert new_calendar.fingerprint != old_calendar.fingerprint
    assert new_cohort._next_slot_index == 50
    _assert_complete_run(rebuilt, new_cohort, new_feeds, planned, new_clock)
    _assert_complete_run(baseline, baseline_cohort, baseline_feeds, planned, baseline_clock)
    _assert_recovered_suffix_matches(
        baseline,
        rebuilt,
        _GAP_INDEX + _RECOVERY_OFFSET,
    )

    gap_batch = rebuilt.batches[_GAP_INDEX]
    assert gap_batch.status == "COMPLETE" and len(gap_batch.members) == len(_ASSETS)
    for asset, feed in new_feeds.items():
        receipt = gap_batch.receipt_for_feed(feed)
        assert receipt is not None and receipt.complete is True
        assert receipt.close_time == planned.minutes[_GAP_INDEX].close_time
        assert receipt.present is (asset != missing_asset)
        assert receipt.quality == ("MISSING" if asset == missing_asset else "GOOD")
    gap_outputs = rebuilt.snapshots[_GAP_INDEX].factors["alpha003"].values
    assert set(gap_outputs) == set(_ASSETS)
    assert all(gap_outputs[asset].present for asset in _ASSETS if asset != missing_asset)
    assert gap_outputs[missing_asset].present is False
    assert gap_outputs[missing_asset].quality == "MISSING"
    assert gap_outputs[missing_asset].status.value == "OUTPUT_UNAVAILABLE"
    assert math.isnan(float(gap_outputs[missing_asset].value))

    factor = parity._factor_for_live(rebuilt)
    missing_column = _ASSETS.index(missing_asset)
    rank_open = factor._nodes["rank_open"].outputs[new_feeds[missing_asset]]
    rank_volume = factor._nodes["rank_volume"].outputs[new_feeds[missing_asset]]
    expected_ineligible = int(parity.operators.OperatorReason.FORMULA_INELIGIBLE)
    assert int(rank_open.reason.array[_GAP_INDEX]) == expected_ineligible
    assert int(rank_volume.reason.array[_GAP_INDEX]) == expected_ineligible
    correlation = factor._nodes["correlation10_%d" % missing_column]
    assert int(correlation.lines.reason.array[_GAP_INDEX + 9]) == int(
        parity.operators.OperatorReason.INCOMPLETE_WINDOW
    )
    not_yet_recovered = rebuilt.snapshots[_GAP_INDEX + 9].factors["alpha003"].values[missing_asset]
    assert not_yet_recovered.status.value == "OUTPUT_UNAVAILABLE"
    assert not_yet_recovered.reason == "INCOMPLETE_WINDOW"
    recovered = (
        rebuilt.snapshots[_GAP_INDEX + _RECOVERY_OFFSET].factors["alpha003"].values[missing_asset]
    )
    assert recovered.status.value == "OUTPUT_AVAILABLE"
    assert recovered.present is True and math.isfinite(float(recovered.value))
