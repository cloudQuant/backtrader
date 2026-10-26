"""Keep a CTP factor feed's first partial-minute guard faithful to observed ticks.

The production Store, Feed, source projector, and calendar run around the
synthetic SDK leaves shared with ``test_ctp_factor_source_cohort``. No provider
or native client is loaded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtrader.events import BarEvent
from backtrader.feeds.ctp_factor_source import CtpFactorSourceError
from backtrader.research.live_cohort import LiveCohortFrozenError, LiveCohortValidationError
from tests.integration import test_ctp_factor_source_cohort as source_fixture
from tests.unit.feeds import test_futures_sessions as session_fixtures


_UTC = timezone.utc
_SHANGHAI = timezone(timedelta(hours=8))


def _system_for_first_common_minute(monkeypatch):
    cu, if_product = session_fixtures.PRODUCTS[0], session_fixtures.PRODUCTS[4]
    products = (cu, if_product)
    grid, _calendars = source_fixture._selected_grid(products)
    first_close = min(minute.close_time for minute in grid.minutes)
    first_bucket_start = first_close - timedelta(minutes=1)
    system = source_fixture._system(
        monkeypatch,
        products=products,
        feed_products=(cu,),
        cohort_close=first_close,
    )
    return system, cu, first_bucket_start, first_close


def _local_text(utc_datetime):
    return utc_datetime.astimezone(_SHANGHAI).replace(tzinfo=None).isoformat(timespec="seconds")


def _emit_at_source_time(
    monkeypatch,
    system,
    product,
    local_time,
    cumulative_volume,
    price=100.0,
    *,
    receive_delay_seconds=0.0,
    **kwargs,
):
    local = datetime.fromisoformat(local_time).replace(tzinfo=_SHANGHAI)
    receive_wall_time = local.timestamp() + receive_delay_seconds
    # The SDK leaf captures a local receipt time. Match that synthetic clock
    # to the chosen source instant so the production freshness checks remain
    # meaningful for these fixed historical calendar fixtures.
    with monkeypatch.context() as patch:
        patch.setattr(source_fixture.time, "time", lambda: receive_wall_time)
        return source_fixture._emit_tick(
            system,
            product,
            local_time,
            cumulative_volume,
            price,
            **kwargs,
        )


def _emit_and_drain(monkeypatch, system, product, utc_time, total, price=100.0):
    _emit_at_source_time(
        monkeypatch,
        system,
        product,
        _local_text(utc_time),
        total,
        price,
    )
    return source_fixture._drain(system.feeds[product])


def _assert_no_published_first_bar(system, product, first_close):
    feed = system.feeds[product]
    first_close_naive_utc = first_close.astimezone(_UTC).replace(tzinfo=None)
    assert feed._bar_sequence == 0
    assert not isinstance(feed._cohort_completed_lookahead, BarEvent)
    assert all(
        builder["bucket_end"] != first_close_naive_utc
        for builder in feed._bar_builders.values()
    )
    assert system.cohort.current_batch() is None
    assert len(feed) == 0


@pytest.mark.integration
def test_preplanned_observation_seeds_first_minute_and_repeats_do_not_shift_or_add_volume(
    monkeypatch,
):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        first_preopen = first_start - timedelta(seconds=90)
        repeated_preopen = first_start - timedelta(seconds=5)
        expected_scope = (system.md_generation, "20261022")
        expected_preopen_bucket = first_preopen.replace(second=0, microsecond=0).replace(
            tzinfo=None
        )
        feed = system.feeds[cu]

        assert _emit_and_drain(monkeypatch, system, cu, first_preopen, 100) is True
        assert feed._ctp_first_bucket_scope == expected_scope
        assert feed._ctp_first_bucket_start == expected_preopen_bucket
        _assert_no_published_first_bar(system, cu, first_close)

        # This is an actual repeated cumulative observation. It has no volume
        # delta and cannot move the first observed bucket marker.
        assert _emit_and_drain(monkeypatch, system, cu, repeated_preopen, 100) is True
        assert feed._ctp_first_bucket_scope == expected_scope
        assert feed._ctp_first_bucket_start == expected_preopen_bucket
        _assert_no_published_first_bar(system, cu, first_close)

        first_close_tick = first_close + timedelta(seconds=5)
        rows = (
            (first_start + timedelta(seconds=5), 103, 100.2),
            (first_start + timedelta(seconds=35), 107, 100.4),
            (first_close_tick, 108, 100.6),
        )
        for timestamp, total, price in rows:
            assert _emit_and_drain(monkeypatch, system, cu, timestamp, total, price) is True

        bar = feed._cohort_completed_lookahead
        assert isinstance(bar, BarEvent)
        assert bar.bucket_start == first_start
        assert bar.bucket_end == first_close
        assert bar.volume == 7.0
        assert (bar.open, bar.high, bar.low, bar.close) == (100.2, 100.4, 100.2, 100.4)
        assert bar.quality == "GOOD"
        assert feed._bar_sequence == 1
        assert system.cohort.current_batch() is None
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
def test_first_planned_minute_is_discarded_without_an_earlier_observation(monkeypatch):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        feed = system.feeds[cu]
        assert feed._ctp_first_bucket_scope is None
        assert feed._ctp_first_bucket_start is None

        # The first cumulative snapshot arrives inside the first planned
        # minute. Its actual bucket becomes the discard marker.
        assert _emit_and_drain(
            monkeypatch,
            system,
            cu,
            first_start + timedelta(seconds=5),
            100,
        ) is True
        assert feed._ctp_first_bucket_scope == (system.md_generation, "20261022")
        assert feed._ctp_first_bucket_start == first_start.replace(tzinfo=None)
        assert _emit_and_drain(
            monkeypatch,
            system,
            cu,
            first_close + timedelta(seconds=5),
            103,
        ) is True
        _assert_no_published_first_bar(system, cu, first_close)
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
def test_same_bucket_cumulative_quotes_cannot_make_the_partial_minute_complete(monkeypatch):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        feed = system.feeds[cu]
        rows = (
            (first_start + timedelta(seconds=5), 100, 100.0),
            (first_start + timedelta(seconds=35), 104, 100.2),
            (first_close + timedelta(seconds=5), 105, 100.4),
        )
        for timestamp, total, price in rows:
            assert _emit_and_drain(monkeypatch, system, cu, timestamp, total, price) is True

        assert feed._ctp_first_bucket_start == first_start.replace(tzinfo=None)
        _assert_no_published_first_bar(system, cu, first_close)
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalidity, expected_failure",
    (
        ("price", "LAST_PRICE_INVALID"),
        ("volume", "CUMULATIVE_VOLUME_INVALID"),
        ("time", "CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID"),
    ),
    ids=("invalid-price", "invalid-cumulative-volume", "malformed-source-time"),
)
def test_invalid_preplanned_source_inputs_cannot_seed_the_first_bucket(
    monkeypatch, invalidity, expected_failure
):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        kwargs = {}
        price = 100.0
        volume = 100
        if invalidity == "price":
            price = 0.0
        elif invalidity == "volume":
            volume = -1
        else:
            kwargs["update_time"] = ""
        _emit_at_source_time(
            monkeypatch,
            system,
            cu,
            _local_text(first_start - timedelta(seconds=5)),
            volume,
            price,
            **kwargs,
        )

        feed = system.feeds[cu]
        queued = system.api._tick_queues[system.aliases[cu]][0]
        error_type = CtpFactorSourceError if invalidity == "time" else LiveCohortValidationError
        with pytest.raises(error_type) as caught:
            source_fixture._drain(feed)
        assert getattr(caught.value, "code", None) == expected_failure
        if invalidity == "volume":
            assert queued.ctp_raw_tick["volume_issue"] == "invalid_cumulative_volume"
        assert feed._ctp_first_bucket_scope is None
        assert feed._ctp_first_bucket_start is None
        assert feed._max_event_timestamp is None
        assert feed._last_ingest_monotonic_ns is None
        assert feed._bar_builders == {}
        assert feed._bar_sequence == 0
        assert not isinstance(feed._cohort_completed_lookahead, BarEvent)
        assert system.cohort.current_batch() is None
        assert first_close > first_start
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
def test_stale_preplanned_observation_does_not_seed_or_poison_event_order(monkeypatch):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        feed = system.feeds[cu]
        timestamp = first_start - timedelta(seconds=5)
        _emit_at_source_time(
            monkeypatch,
            system,
            cu,
            _local_text(timestamp),
            100,
            receive_delay_seconds=10.0,
        )
        assert source_fixture._drain(feed) is True
        assert feed._ctp_first_bucket_scope is None
        assert feed._ctp_first_bucket_start is None
        assert feed._max_event_timestamp is None
        assert feed._last_ingest_monotonic_ns is None
        _assert_no_published_first_bar(system, cu, first_close)
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
def test_unhealthy_preplanned_observation_does_not_seed_or_poison_event_order(monkeypatch):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        feed = system.feeds[cu]
        _emit_at_source_time(
            monkeypatch,
            system,
            cu,
            _local_text(first_start - timedelta(seconds=5)),
            100,
        )
        event = system.api._tick_queues[system.aliases[cu]][0]
        event.stale = True

        with pytest.raises(LiveCohortFrozenError):
            source_fixture._drain(feed)
        assert feed._ctp_first_bucket_scope is None
        assert feed._ctp_first_bucket_start is None
        assert feed._max_event_timestamp is None
        assert feed._last_ingest_monotonic_ns is None
        assert feed._bar_builders == {}
        assert feed._bar_sequence == 0
        assert not isinstance(feed._cohort_completed_lookahead, BarEvent)
        assert system.cohort.current_batch() is None
        assert first_close > first_start
    finally:
        source_fixture._close_system(system)


@pytest.mark.integration
def test_explicit_quote_only_winddown_does_not_seed_the_first_bucket(monkeypatch):
    system, cu, first_start, first_close = _system_for_first_common_minute(monkeypatch)
    try:
        feed = system.feeds[cu]
        _emit_at_source_time(
            monkeypatch,
            system,
            cu,
            _local_text(first_start - timedelta(seconds=5)),
            100,
        )
        assert feed._drain_live_ticks(limit=32, stop_after_queued_bar=False, quote_only=True) == 1
        assert feed._ctp_first_bucket_scope is None
        assert feed._ctp_first_bucket_start is None
        assert feed._bar_builders == {}
        assert feed._bar_sequence == 0
        assert not isinstance(feed._cohort_completed_lookahead, BarEvent)
        assert system.cohort.current_batch() is None
        assert first_close > first_start
    finally:
        source_fixture._close_system(system)
