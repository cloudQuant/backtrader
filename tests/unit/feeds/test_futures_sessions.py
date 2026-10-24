"""Explicit public calendar/session inputs produce a fixed all-member grid."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib

import pytest

import backtrader.feeds.futures_sessions as futures_sessions
from backtrader.feeds.futures_main_contract import ProductKey
from backtrader.feeds.futures_sessions import (
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionCalendarError,
    SessionWindow,
    build_common_minute_grid,
    find_planned_common_minute,
    load_exchange_session_calendar,
)


CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
UTC = timezone.utc
TRADING_DAY = date(2026, 10, 22)
DECISION_AT = datetime(2026, 10, 23, 0, tzinfo=UTC)


def _local(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=CHINA)


def _source(source_id, *, available_at=None, retrieved_at=None):
    available = available_at or datetime(2026, 10, 20, 0, tzinfo=UTC)
    retrieved = retrieved_at or datetime(2026, 10, 20, 1, tzinfo=UTC)
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    return PublicSourceEvidence(
        source_id=source_id,
        source_url="https://fixture.invalid/{}.html".format(source_id),
        version="fixture-2026-10-20",
        available_at=available,
        retrieved_at=retrieved,
        sha256=digest,
    )


DAY_WINDOWS = (
    ("day-am-1", 9, 0, 10, 15),
    ("day-am-2", 10, 30, 11, 30),
    ("day-pm", 13, 30, 15, 0),
)


def _day_windows(product, source_id, trading_day=TRADING_DAY):
    if product.exchange_id == "CFFEX":
        intervals = (
            ("day-am", 9, 30, 11, 30),
            ("day-pm", 13, 0, 15, 0),
        )
    else:
        intervals = DAY_WINDOWS
    return tuple(
        SessionWindow(
            session_id=session_id,
            session_date=trading_day,
            start=_local(trading_day, start_hour, start_minute),
            end=_local(trading_day, end_hour, end_minute),
            source_id=source_id,
        )
        for session_id, start_hour, start_minute, end_hour, end_minute in intervals
    )


def _night_window(product, source_id, *, end_hour, end_minute=0):
    session_date = TRADING_DAY - timedelta(days=1)
    end_day = TRADING_DAY if end_hour < 21 else session_date
    return SessionWindow(
        session_id="night",
        session_date=session_date,
        start=_local(session_date, 21),
        end=_local(end_day, end_hour, end_minute),
        source_id=source_id,
    )


def _exchange_calendar(
    exchange_id,
    product,
    *,
    day=TRADING_DAY,
    night_end=None,
    complete=True,
    include_row=True,
    retrieved_at=None,
    available_at=None,
):
    calendar_id = "{}.calendar".format(exchange_id)
    session_id = "{}.hours".format(exchange_id)
    sources = (
        _source(calendar_id, available_at=available_at, retrieved_at=retrieved_at),
        _source(session_id, available_at=available_at, retrieved_at=retrieved_at),
    )
    windows = list(_day_windows(product, session_id, day))
    if night_end is not None:
        end_hour, end_minute = night_end if isinstance(night_end, tuple) else (night_end, 0)
        windows.insert(
            0,
            _night_window(
                product,
                session_id,
                end_hour=end_hour,
                end_minute=end_minute,
            ),
        )
    rows = (
        (
            ProductTradingDaySessions(
                product=product,
                trading_day=day,
                source_id=session_id,
                windows=tuple(windows),
            ),
        )
        if include_row
        else ()
    )
    return ExchangeSessionCalendar(
        exchange_id=exchange_id,
        calendar_source_id=calendar_id,
        coverage_start=day,
        coverage_through=day,
        trading_days=(day,),
        product_universe=(product,),
        product_days=rows,
        sources=sources,
        complete=complete,
    )


PRODUCTS = (
    ProductKey("SHFE", "CU"),
    ProductKey("INE", "SC"),
    ProductKey("DCE", "M"),
    ProductKey("CZCE", "CF"),
    ProductKey("CFFEX", "IF"),
    ProductKey("GFEX", "SI"),
)


def _six_exchange_calendars():
    return (
        _exchange_calendar("SHFE", PRODUCTS[0], night_end=1),
        _exchange_calendar("INE", PRODUCTS[1], night_end=(2, 30)),
        _exchange_calendar("DCE", PRODUCTS[2], night_end=23),
        _exchange_calendar("CZCE", PRODUCTS[3], night_end=23),
        _exchange_calendar("CFFEX", PRODUCTS[4]),
        _exchange_calendar("GFEX", PRODUCTS[5]),
    )


def _product_days(products=PRODUCTS, day=TRADING_DAY):
    return dict.fromkeys(products, (day,))


def test_six_exchange_fixture_intersects_full_target_and_emits_only_common_day_minutes():
    grid = build_common_minute_grid(
        PRODUCTS,
        _six_exchange_calendars(),
        _product_days(),
        decision_at=DECISION_AT,
    )

    assert grid.status == "READY"
    assert grid.target_products == PRODUCTS
    assert len(grid.minutes) == 195
    closes = [minute.close_time for minute in grid.minutes]
    assert closes[0] == datetime(2026, 10, 22, 1, 31, tzinfo=UTC)
    assert closes[-1] == datetime(2026, 10, 22, 7, 0, tzinfo=UTC)
    assert all(len(minute.members) == len(PRODUCTS) for minute in grid.minutes)
    assert all(
        tuple(member.product for member in minute.members) == PRODUCTS for minute in grid.minutes
    )
    # The day-only members remove all night minutes; the day break is not filled.
    assert not any(
        datetime(2026, 10, 21, 13, 0, tzinfo=UTC)
        <= close
        <= datetime(2026, 10, 22, 0, 59, tzinfo=UTC)
        for close in closes
    )
    assert not any(
        datetime(2026, 10, 22, 2, 16, tzinfo=UTC)
        <= close
        <= datetime(2026, 10, 22, 2, 30, tzinfo=UTC)
        for close in closes
    )
    assert grid.to_dict()["target_products"][-1] == {
        "exchange_id": "GFEX",
        "product_id": "SI",
    }


def test_night_intersection_uses_shortest_actual_product_session():
    products = PRODUCTS[:3]
    calendars = _six_exchange_calendars()[:3]
    grid = build_common_minute_grid(
        products,
        calendars,
        _product_days(products),
        decision_at=DECISION_AT,
    )

    assert len(grid.minutes) == 345  # 120 night + 225 day minutes.
    night = [minute for minute in grid.minutes if minute.members[0].session_id == "night"]
    assert len(night) == 120
    assert night[-1].close_time == datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    assert all(
        member.trading_day == TRADING_DAY and member.session_date == date(2026, 10, 21)
        for member in night[-1].members
    )


def test_overnight_slot_preserves_session_date_action_day_and_trading_day():
    products = PRODUCTS[:2]
    grid = build_common_minute_grid(
        products,
        _six_exchange_calendars()[:2],
        _product_days(products),
        decision_at=DECISION_AT,
    )
    slot = next(
        minute
        for minute in grid.minutes
        if minute.close_time == datetime(2026, 10, 21, 16, 30, tzinfo=UTC)
    )

    assert [member.session_date for member in slot.members] == [date(2026, 10, 21)] * 2
    assert [member.action_day for member in slot.members] == [date(2026, 10, 22)] * 2
    assert [member.trading_day for member in slot.members] == [TRADING_DAY] * 2


def test_no_night_is_sourced_explicitly_for_first_day_after_holiday():
    product = ProductKey("SHFE", "CU")
    resumed_day = date(2026, 1, 5)
    source_calendar = _source("SHFE.2026-holiday").source_id
    source_hours = "SHFE.hours"
    session_source = _source(source_hours)
    calendar_source = _source(source_calendar)
    windows = _day_windows(product, source_hours, resumed_day)
    snapshot = ExchangeSessionCalendar(
        exchange_id="SHFE",
        calendar_source_id=source_calendar,
        coverage_start=date(2025, 12, 31),
        coverage_through=resumed_day,
        trading_days=(date(2025, 12, 31), resumed_day),
        product_universe=(product,),
        product_days=(
            ProductTradingDaySessions(
                product=product,
                trading_day=resumed_day,
                source_id=source_calendar,
                windows=windows,
            ),
        ),
        sources=(calendar_source, session_source),
    )
    grid = build_common_minute_grid(
        (product,),
        (snapshot,),
        {product: (resumed_day,)},
        decision_at=DECISION_AT,
    )

    assert grid.status == "READY"
    assert len(grid.minutes) == 225
    assert all(minute.members[0].session_id != "night" for minute in grid.minutes)


def test_missing_exchange_product_or_product_day_coverage_is_not_silently_dropped():
    with pytest.raises(SessionCalendarError, match="EXCHANGE_CALENDAR_MISSING"):
        build_common_minute_grid(
            PRODUCTS,
            _six_exchange_calendars()[:-1],
            _product_days(),
            decision_at=DECISION_AT,
        )

    calendars = list(_six_exchange_calendars())
    calendars[-1] = replace(calendars[-1], product_universe=(), product_days=())
    with pytest.raises(SessionCalendarError, match="PRODUCT_SESSION_UNIVERSE_MISSING"):
        build_common_minute_grid(
            PRODUCTS,
            calendars,
            _product_days(),
            decision_at=DECISION_AT,
        )

    calendars = list(_six_exchange_calendars())
    calendars[-1] = replace(calendars[-1], product_days=())
    with pytest.raises(SessionCalendarError, match="PRODUCT_SESSION_ROW_MISSING"):
        build_common_minute_grid(
            PRODUCTS,
            calendars,
            _product_days(),
            decision_at=DECISION_AT,
        )


def test_weekday_absent_from_explicit_source_calendar_is_rejected():
    product = PRODUCTS[0]
    snapshot = _exchange_calendar("SHFE", product)
    unlisted_weekday = date(2026, 10, 23)
    snapshot = replace(snapshot, coverage_through=unlisted_weekday)
    with pytest.raises(SessionCalendarError, match="TRADING_DAY_NOT_IN_SOURCE_CALENDAR"):
        build_common_minute_grid(
            (product,),
            (snapshot,),
            {product: (unlisted_weekday,)},
            decision_at=DECISION_AT,
        )


def test_incomplete_calendar_and_future_retrieval_are_rejected():
    product = PRODUCTS[0]
    incomplete = _exchange_calendar("SHFE", product, complete=False)
    with pytest.raises(SessionCalendarError, match="EXCHANGE_CALENDAR_INCOMPLETE"):
        build_common_minute_grid(
            (product,), (incomplete,), {product: (TRADING_DAY,)}, decision_at=DECISION_AT
        )

    retrieved_late = _exchange_calendar(
        "SHFE",
        product,
        retrieved_at=datetime(2026, 10, 23, 1, tzinfo=UTC),
    )
    with pytest.raises(SessionCalendarError, match="SESSION_SOURCE_RETRIEVED_AFTER_DECISION"):
        build_common_minute_grid(
            (product,),
            (retrieved_late,),
            {product: (TRADING_DAY,)},
            decision_at=DECISION_AT,
        )


def test_calendar_facts_adapt_to_the_existing_selector_without_weekday_generation():
    snapshot = _exchange_calendar("SHFE", PRODUCTS[0])
    calendar = snapshot.to_main_contract_calendar()

    assert calendar.exchange_id == "SHFE"
    assert calendar.trading_days == (TRADING_DAY,)
    assert calendar.complete is True
    assert calendar.source_id == "SHFE.calendar"


def test_snapshot_hash_is_deterministic_across_source_row_order():
    snapshots = _six_exchange_calendars()
    original = snapshots[0]
    reordered = replace(
        original,
        product_days=tuple(reversed(original.product_days)),
        sources=tuple(reversed(original.sources)),
    )

    assert reordered.evidence_sha256 == original.evidence_sha256


def test_public_calendar_json_roundtrip_keeps_provenance_and_explicit_dates():
    original = _six_exchange_calendars()[0]

    restored = load_exchange_session_calendar(original.to_dict())

    assert restored == original
    assert restored.evidence_sha256 == original.evidence_sha256
    assert restored.to_main_contract_calendar().trading_days == (TRADING_DAY,)


def test_session_source_available_after_decision_blocks_the_whole_grid():
    product = PRODUCTS[0]
    late = _exchange_calendar(
        "SHFE",
        product,
        available_at=datetime(2026, 10, 23, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 23, 2, tzinfo=UTC),
    )
    with pytest.raises(SessionCalendarError, match="SESSION_SOURCE_NOT_AVAILABLE_AT_DECISION"):
        build_common_minute_grid(
            (product,),
            (late,),
            {product: (TRADING_DAY,)},
            decision_at=DECISION_AT,
        )


def test_session_source_times_and_minute_boundaries_are_validated():
    with pytest.raises(ValueError, match="China UTC\+08:00"):
        SessionWindow(
            session_id="bad-offset",
            session_date=TRADING_DAY,
            start=datetime(2026, 10, 22, 9, tzinfo=UTC),
            end=datetime(2026, 10, 22, 10, tzinfo=UTC),
            source_id="x",
        )

    with pytest.raises(ValueError, match="whole minutes"):
        SessionWindow(
            session_id="bad-boundary",
            session_date=TRADING_DAY,
            start=_local(TRADING_DAY, 9, 0) + timedelta(seconds=1),
            end=_local(TRADING_DAY, 10),
            source_id="x",
        )

    with pytest.raises(ValueError, match="no longer than 24 hours"):
        SessionWindow(
            session_id="too-long",
            session_date=TRADING_DAY,
            start=_local(TRADING_DAY, 0),
            end=_local(TRADING_DAY + timedelta(days=1), 0, 1),
            source_id="x",
        )


def test_planned_close_lookup_returns_exact_frozen_member_evidence():
    product = PRODUCTS[0]
    grid = build_common_minute_grid(
        (product,),
        (_exchange_calendar("SHFE", product),),
        {product: (TRADING_DAY,)},
        decision_at=DECISION_AT,
    )
    planned = grid.minutes[0]
    equivalent_local_time = planned.close_time.astimezone(CHINA)

    assert find_planned_common_minute(grid, planned.close_time) is planned
    assert find_planned_common_minute(grid, equivalent_local_time) is planned
    assert find_planned_common_minute(grid, planned.close_time + timedelta(seconds=1)) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        find_planned_common_minute(grid, planned.close_time.replace(tzinfo=None))


def test_session_json_window_count_is_bounded_before_window_objects_are_created():
    document = _six_exchange_calendars()[0].to_dict()
    windows = document["product_days"][0]["windows"]
    document["product_days"][0]["windows"] = [dict(windows[0])] * 17

    with pytest.raises(SessionCalendarError, match="INPUT_LIMIT_EXCEEDED"):
        load_exchange_session_calendar(document)


def test_session_json_product_day_count_is_bounded_before_rows_are_walked():
    class OversizedRows(list):
        def __len__(self):
            return 100_001

        def __iter__(self):
            raise AssertionError("oversized rows must be rejected before iteration")

    document = _six_exchange_calendars()[0].to_dict()
    document["product_days"] = OversizedRows()

    with pytest.raises(SessionCalendarError, match="INPUT_LIMIT_EXCEEDED"):
        load_exchange_session_calendar(document)


def test_grid_expansion_budget_is_checked_before_minute_slot_expansion(monkeypatch):
    product = ProductKey("SHFE", "CU")
    first_day = date(2020, 1, 1)
    days = tuple(first_day + timedelta(days=offset) for offset in range(695))
    calendar_id = "SHFE.calendar"
    session_id = "SHFE.hours"
    sources = (_source(calendar_id), _source(session_id))
    rows = tuple(
        ProductTradingDaySessions(
            product=product,
            trading_day=day,
            source_id=session_id,
            windows=(
                SessionWindow(
                    session_id="full-day",
                    session_date=day,
                    start=_local(day, 0),
                    end=_local(day + timedelta(days=1), 0),
                    source_id=session_id,
                ),
            ),
        )
        for day in days
    )
    calendar = ExchangeSessionCalendar(
        exchange_id="SHFE",
        calendar_source_id=calendar_id,
        coverage_start=days[0],
        coverage_through=days[-1],
        trading_days=days,
        product_universe=(product,),
        product_days=rows,
        sources=sources,
    )

    def should_not_expand(_row):
        pytest.fail("budget must be checked before minute slot expansion")

    monkeypatch.setattr(futures_sessions, "_minute_slots", should_not_expand)
    with pytest.raises(SessionCalendarError, match="GRID_EXPANSION_BUDGET_EXCEEDED"):
        build_common_minute_grid(
            (product,),
            (calendar,),
            {product: days},
            decision_at=DECISION_AT,
        )
