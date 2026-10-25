"""Rule-derived common closes remain intact across a real cohort lunch break."""

from __future__ import annotations

import datetime as dt
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.feeds.futures_expected_calendar import (
    EXPECTED_RULE_EVIDENCE_MODE,
    build_expected_daytime_calendars,
)
from backtrader.feeds.futures_main_contract import ProductKey
from backtrader.feeds.futures_sessions import build_common_minute_grid
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)


_UTC = dt.timezone.utc
_CHINA = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
_TRADING_DAY = dt.date(2026, 10, 26)
_PRODUCTS = (ProductKey("DCE", "M"), ProductKey("SHFE", "CU"))
_CLOCK_DOMAIN = "expected-calendar-cohort-gap-test-v1"
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class _ReplayClock:
    """Advance source time only when ordinary Cerebro waits for a cohort slot."""

    def __init__(self, now: dt.datetime):
        self.now = now
        self.monotonic = 1_000_000_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        timeout = float(timeout_seconds)
        assert math.isfinite(timeout) and timeout >= 0
        self.waits.append(timeout)
        self.monotonic += max(1, int(timeout * 1_000_000_000))
        if timeout:
            self.now += dt.timedelta(seconds=timeout)


class _BatchCapture(bt.Strategy):
    params = (("cohort", None),)

    def __init__(self):
        self.received = []

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.received.append(
            (
                batch,
                tuple(len(data) for data in self.datas),
                tuple(float(data.close[0]) for data in self.datas),
            )
        )


def _planner_slots():
    available_at = dt.datetime(2026, 10, 23, 23, 55, tzinfo=_UTC)
    expected = build_expected_daytime_calendars(
        _PRODUCTS,
        dict.fromkeys((product.exchange_id for product in _PRODUCTS), _TRADING_DAY),
        as_of=available_at + dt.timedelta(minutes=5),
        retrieved_at=available_at,
    )
    assert expected.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
    assert expected.rules_manifest_sha256

    grid = build_common_minute_grid(
        _PRODUCTS,
        expected.session_calendars,
        dict.fromkeys(_PRODUCTS, (_TRADING_DAY,)),
        decision_at=available_at + dt.timedelta(minutes=5),
    )
    assert grid.status == "READY"
    assert grid.target_products == _PRODUCTS

    by_local_close = {
        planned.close_time.astimezone(_CHINA).strftime("%H:%M"): planned for planned in grid.minutes
    }
    # 13:34 remains beyond the required 13:33 lookahead so the bounded replay
    # source stays open while the 13:32 missing-member deadline is evaluated.
    closes = ("11:30", "13:31", "13:32", "13:33", "13:34")
    assert all(close in by_local_close for close in closes)
    planned_slots = tuple(by_local_close[close] for close in closes)
    assert planned_slots[1].close_time - planned_slots[0].close_time == dt.timedelta(
        hours=2, minutes=1
    )
    assert all(
        right.close_time - left.close_time == dt.timedelta(minutes=1)
        for left, right in zip(planned_slots[1:], planned_slots[2:])
    )
    return expected, grid, planned_slots


def _cohort_calendar(planned_slots):
    member_ids = {
        product: "member:{}".format(product.exchange_id + "." + product.product_id)
        for product in _PRODUCTS
    }
    slots = []
    for index, planned in enumerate(planned_slots):
        evidence_by_product = {evidence.product: evidence for evidence in planned.members}
        assert set(evidence_by_product) == set(_PRODUCTS)
        member_sessions = {
            member_ids[product]: LiveCalendarMemberSession(
                trading_day=evidence_by_product[product].trading_day.strftime("%Y%m%d"),
                session_segment=evidence_by_product[product].session_id,
            )
            for product in _PRODUCTS
        }
        first_member = evidence_by_product[_PRODUCTS[0]]
        # No planner-to-cohort converter exists. Map the public plan one-for-one:
        # preserve its UTC close and each product's exact rule-derived session
        # evidence, with the 1-minute bucket start derived from its close.
        slots.append(
            LiveCalendarSlot(
                slot_id="rule-planned-{}".format(planned.close_time.isoformat()),
                bucket_start=planned.close_time - dt.timedelta(minutes=1),
                close_time=planned.close_time,
                trading_day=first_member.trading_day.strftime("%Y%m%d"),
                session_segment=first_member.session_id,
                member_sessions=member_sessions,
            )
        )
    calendar = LiveCohortCalendar(
        calendar_id="expected-rule-common-minute-v1",
        version="2026-rules-{}".format(_TRADING_DAY.isoformat()),
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id=_CLOCK_DOMAIN,
        session_semantics="expected-rule-member-session-v1",
        slots=tuple(slots),
    )
    return calendar, member_ids


def _bar_event(product, slot, member_session, *, sequence):
    close = float(100 + sequence + (0 if product.exchange_id == "DCE" else 10))
    return {
        "instrument": "{}.{}".format(product.exchange_id, product.product_id),
        "symbol": "{}.{}".format(product.exchange_id, product.product_id),
        "timestamp": slot.close_time.timestamp(),
        "datetime": slot.close_time,
        "bucket_start": slot.bucket_start,
        "bucket_end": slot.close_time,
        "available_at": slot.close_time,
        "trading_day": member_session.trading_day,
        "session_segment": member_session.session_segment,
        "timezone_id": "UTC",
        "clock_domain_id": _CLOCK_DOMAIN,
        "connection_generation": "fixture-generation-1",
        "bar_sequence": sequence,
        "bar_id": "{}:{}".format(product.product_id, sequence),
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": float(1000 + sequence),
        "openinterest": 0.0,
        "present": True,
        "complete": True,
        "quality": "GOOD",
        "quality_flags": (),
        "source": "expected-calendar-fixture",
    }


@pytest.mark.integration
def test_rule_common_grid_lunch_closure_is_not_gap_but_missing_due_slot_freezes_without_compression():
    expected, grid, planned = _planner_slots()
    calendar, member_ids = _cohort_calendar(planned)
    cohort = LiveBarCohort(
        "expected-calendar-cohort-gap",
        calendar,
        max_pending_slots=2,
        max_window_bars=len(planned),
        wait_timeout_ns=2_000_000,
    )
    clock = _ReplayClock(planned[0].close_time)
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}

    for product in _PRODUCTS:
        member_id = member_ids[product]
        rows = []
        for slot_index, slot in enumerate(calendar.slots):
            if product == _PRODUCTS[1] and slot_index == 2:
                continue
            rows.append(
                MappingProxyType(
                    _bar_event(
                        product,
                        slot,
                        slot.member_sessions[member_id],
                        sequence=slot_index + 1,
                    )
                )
            )
        feed = bt.feeds.BtApiFeed(
            dataname=member_id,
            historical_bars=(),
            live_bars=tuple(rows),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[product] = feed
        cerebro.adddata(feed, name=member_id)
        cohort.register_member(
            member_id,
            feed,
            instrument="{}.{}".format(product.exchange_id, product.product_id),
            source_ref="expected-rule-fixture:{}".format(member_id),
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )

    cohort.seal()
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(_BatchCapture, cohort=cohort)
    strategy = cerebro.run(runonce=False, preload=False)[0]

    assert expected.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
    assert grid.minutes
    assert tuple(record[0].close_time for record in strategy.received) == tuple(
        slot.close_time for slot in planned[:2]
    )
    assert tuple(record[0].slot_index for record in strategy.received) == (0, 1)
    assert tuple(record[1] for record in strategy.received) == ((1, 1), (2, 2))
    assert tuple(record[2] for record in strategy.received) == ((101.0, 111.0), (102.0, 112.0))

    # The long scheduled closure is a wait between two adjacent emitted rows,
    # not a missing planned minute. The next actual planned omission freezes
    # the same epoch before any feed line or Strategy callback can advance.
    lunch_waits = tuple(timeout for timeout in clock.waits if timeout >= 3600)
    assert len(lunch_waits) == 1
    assert math.isclose(lunch_waits[0], 2 * 3600 + 60, rel_tol=0.0, abs_tol=1e-6)
    assert cohort.frozen is True
    assert cohort.frozen_reason == "planned_gap_requires_rebuild"
    assert len(cohort.gaps) == 1
    gap = cohort.gaps[0]
    assert gap.slot_index == 2
    assert gap.slot_id == calendar.slots[2].slot_id
    assert gap.close_time == planned[2].close_time
    assert gap.missing_member_ids == (member_ids[_PRODUCTS[1]],)
    assert tuple(item.slot_index for item in cohort.gaps) == (2,)
    assert set(cohort._pending[3]) == set(member_ids.values())
    assert {envelope.close_time for envelope in cohort._pending[3].values()} == {
        planned[3].close_time
    }
    assert cohort._next_slot_index == 2
    assert cohort.current_batch() is strategy.received[-1][0]
    assert cohort.current_batch().slot_index == 1
    assert tuple(len(feed) for feed in feeds.values()) == (2, 2)
    assert tuple(record[0].slot_index for record in strategy.received) == (0, 1)
