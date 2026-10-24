"""Direct RegisteredSim CTP callback to Store/Feed raw-tick contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)
from backtrader.stores.registered_sim import RegisteredSimStore

UTC = timezone.utc


class _Clock:
    def utc_now(self):
        return datetime(2026, 10, 23, 1, 30, tzinfo=UTC)

    def monotonic_ns(self):
        return 1_000_000_000

    def wait(self, _timeout):
        return None


def _payload(time_text, volume, *, day="20261023", price=100.0, millisec=0):
    return SimpleNamespace(
        InstrumentID="rb2611",
        ExchangeID="SHFE",
        LastPrice=price,
        Volume=volume,
        BidPrice1=99.0,
        AskPrice1=101.0,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay=day,
        ActionDay=day,
        UpdateTime=time_text,
        UpdateMillisec=millisec,
    )


def _store(monkeypatch, rows):
    ctp_client = pytest.importorskip("bt_api_ctp.ctp.client")

    class _FakeMdClient:
        def __init__(self, **_kwargs):
            self.on_tick = None
            self.on_error = None
            self._connection_generation = 0
            self.payloads = tuple(rows)

        def start(self, block=False):
            assert block is False
            for generation, payload in self.payloads:
                self._connection_generation = generation
                self.on_tick(payload)

        def wait_ready(self, timeout=20):
            return True

        def subscribe(self, _instruments):
            return None

        def stop(self):
            return None

    class _FakeTraderClient:
        is_ready = False

        def __init__(self, **_kwargs):
            self.on_login = None
            self.on_order = None
            self.on_trade = None
            self.on_error = None

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            return True

        def get_session_state(self):
            return {
                "connected": True,
                "ready": False,
                "auth_state": "unknown",
                "login_state": "unknown",
            }

        def stop(self):
            return None

    monkeypatch.setattr(ctp_client, "MdClient", _FakeMdClient)
    monkeypatch.setattr(ctp_client, "TraderClient", _FakeTraderClient)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID", raising=False)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_SECRET", raising=False)
    return RegisteredSimStore(
        provider="ctp",
        backend="direct",
        preserve_raw_bars=True,
        broker_id="test-broker",
        user_id="test-user",
        investor_id="test-user",
        password="test-password",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        auto_settlement_confirm=False,
    )


def _strict_feed(store):
    from backtrader.feeds.btapifeed import BtApiFeed

    close = datetime(2026, 10, 23, 1, 31, tzinfo=UTC)
    calendar = LiveCohortCalendar(
        calendar_id="ac51-07-calendar",
        version="fixture-v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="ac51-07-clock",
        session_semantics="ac51-07-session",
        slots=(
            LiveCalendarSlot(
                slot_id="slot-0",
                bucket_start=close - timedelta(minutes=1),
                close_time=close,
                trading_day="20261023",
                session_segment="day",
                member_sessions={"member-rb": LiveCalendarMemberSession("20261023", "day")},
            ),
        ),
    )
    cohort = LiveBarCohort(
        "ac51-07-cohort",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=1_000_000_000,
    )
    feed = BtApiFeed(
        dataname="rb2611",
        store=store,
        cohort_source_mode=True,
        backfill_start=False,
        historical_bars=(),
        live_bars=(),
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        clock=_Clock(),
    )
    cohort.register_member(
        "member-rb",
        feed,
        instrument="SHFE.rb2611",
        source_ref="registered-sim-rb2611",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    cohort.seal()
    prepared = feed._prepare_live_bar_cohort_activation(cohort, _Clock())
    feed._commit_live_bar_cohort_activation(prepared)
    return feed, cohort


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad_price, expected_category",
    [
        (None, "missing"),
        (math.nan, "nan"),
        (math.inf, "non_finite"),
        ("bad", "wrong_type"),
    ],
    ids=("none", "nan", "infinity", "wrong-type"),
)
def test_registered_sim_raw_price_reaches_strict_feed_before_coercion(
    monkeypatch, bad_price, expected_category
):
    store = _store(monkeypatch, ((7, _payload("09:30:05", 100, price=bad_price)),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "LAST_PRICE_INVALID"
        assert caught.value.report["source"] == "BtApiFeed.ctp_tick"
        assert caught.value.report["field"] == "LastPrice"
        assert caught.value.report["category"] == expected_category
        assert caught.value.report["generation"] == 7
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_tick_price"
        assert len(feed) == 0
        latest = store.get_latest_tick_snapshot("rb2611")
        assert latest.source == store.registered_sim_tick_source
        raw_price = latest.ctp_raw_tick["LastPrice"]
        assert raw_price is bad_price or (
            isinstance(bad_price, float) and math.isnan(bad_price) and math.isnan(raw_price)
        )
        assert latest.timestamp > 0
    finally:
        store.stop()


@pytest.mark.integration
@pytest.mark.parametrize(
    "time_text, action_day, trading_day",
    [
        ("", "20261023", "20261023"),
        ("bad-time", "20261023", "20261023"),
    ],
    ids=("missing-time", "bad-time"),
)
def test_registered_sim_invalid_source_time_is_not_replaced_with_local_time(
    monkeypatch, time_text, action_day, trading_day
):
    payload = _payload(time_text, 100)
    payload.ActionDay = action_day
    payload.TradingDay = trading_day
    store = _store(monkeypatch, ((7, payload),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "SOURCE_TIME_INVALID"
        assert caught.value.report["field"] == "source_time"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_tick_time"
        latest = store.get_latest_tick_snapshot("rb2611")
        assert latest.timestamp == 0.0
        assert latest.datetime is None
        assert latest.ctp_raw_tick["UpdateTime"] == time_text
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_strict_path_rejects_invalid_trading_day(monkeypatch):
    payload = _payload("09:30:05", 100)
    payload.TradingDay = "20261032"
    store = _store(monkeypatch, ((7, payload),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "TRADING_DAY_INVALID"
        assert caught.value.report["field"] == "TradingDay"
        assert caught.value.report["category"] == "invalid_date"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_trading_day"
        latest = store.get_latest_tick_snapshot("rb2611")
        assert latest.ctp_raw_tick["TradingDay"] == "20261032"
        assert latest.ctp_raw_tick["ActionDay"] == "20261023"
    finally:
        store.stop()


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad_volume, expected_category",
    [
        (None, "missing"),
        (math.nan, "nan"),
        (-1, "negative"),
        ("bad", "wrong_type"),
    ],
    ids=("none", "nan", "negative", "wrong-type"),
)
def test_registered_sim_invalid_cumulative_volume_is_rejected_before_bar_building(
    monkeypatch, bad_volume, expected_category
):
    store = _store(monkeypatch, ((7, _payload("09:30:05", bad_volume)),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "CUMULATIVE_VOLUME_INVALID"
        assert caught.value.report["field"] == "Volume"
        assert caught.value.report["category"] == expected_category
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_cumulative_volume"
        assert len(feed) == 0
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_cumulative_rollback_freezes_the_strict_cohort(monkeypatch):
    rows = (
        (7, _payload("09:30:05", 100)),
        (7, _payload("09:30:06", 98, millisec=1)),
    )
    store = _store(monkeypatch, rows)
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        assert feed._drain_live_ticks(limit=1) is True
        first = store.get_latest_tick_snapshot("rb2611")
        expected = datetime(
            2026,
            10,
            23,
            9,
            30,
            5,
            tzinfo=timezone(timedelta(hours=8)),
        )
        assert first.timestamp == expected.timestamp()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "VOLUME_DISCONTINUITY"
        assert caught.value.report["category"] == "cumulative_volume_rollback"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_cumulative_volume"
        assert len(feed) == 0
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_out_of_order_tick_freezes_without_replacing_volume_baseline(monkeypatch):
    rows = (
        (7, _payload("09:30:06", 100, millisec=900)),
        (7, _payload("09:30:06", 101, millisec=100)),
    )
    store = _store(monkeypatch, rows)
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        assert feed._drain_live_ticks(limit=1) is True
        first = store.get_latest_tick_snapshot("rb2611")
        expected = datetime(
            2026,
            10,
            23,
            9,
            30,
            6,
            900_000,
            tzinfo=timezone(timedelta(hours=8)),
        )
        assert first.timestamp == expected.timestamp()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "VOLUME_DISCONTINUITY"
        assert caught.value.report["category"] == "out_of_order"
        assert cohort.frozen is True
        assert len(feed) == 0
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_strict_path_rejects_bad_action_day_with_valid_trading_day(monkeypatch):
    payload = _payload("09:30:05", 100)
    payload.ActionDay = "2026-10-23"
    payload.TradingDay = "20261023"
    store = _store(monkeypatch, ((7, payload),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "ACTION_DAY_INVALID"
        assert caught.value.report["field"] == "ActionDay"
        assert caught.value.report["category"] == "missing_or_invalid"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_action_day"
        latest = store.get_latest_tick_snapshot("rb2611")
        assert latest.ctp_raw_tick["ActionDay"] == "2026-10-23"
        assert latest.ctp_raw_tick["TradingDay"] == "20261023"
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_strict_path_rejects_action_day_getter_error(monkeypatch):
    class _UnreadableActionDay:
        def __init__(self, source):
            self._source = source

        @property
        def ActionDay(self):
            raise AttributeError("fixture getter failure")

        def __getattr__(self, name):
            if name == "ActionDay":
                raise AttributeError("fixture getter failure")
            return getattr(self._source, name)

    payload = _UnreadableActionDay(_payload("09:30:05", 100))
    store = _store(monkeypatch, ((7, payload),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "ACTION_DAY_INVALID"
        assert caught.value.report["field"] == "ActionDay"
        assert caught.value.report["category"] == "read_error"
        assert cohort.frozen is True
        latest = store.get_latest_tick_snapshot("rb2611")
        assert latest.ctp_raw_tick["ActionDay"] == {"read_error": True}
    finally:
        store.stop()


@pytest.mark.integration
@pytest.mark.parametrize(
    "time_text, trading_day, action_day, delete_action_day",
    [
        ("09:30:05", "20261023", None, True),
        ("09:30:05", "20261023", "", False),
        ("21:00:00", "20261026", None, True),
        ("00:30:00", "20261026", None, True),
    ],
    ids=(
        "daytime-absent",
        "daytime-empty",
        "overnight-date-unknown",
        "after-midnight-date-unknown",
    ),
)
def test_registered_sim_strict_path_rejects_unproven_action_day(
    monkeypatch, time_text, trading_day, action_day, delete_action_day
):
    payload = _payload(time_text, 100, day=trading_day)
    if delete_action_day:
        del payload.ActionDay
    else:
        payload.ActionDay = action_day
    store = _store(monkeypatch, ((7, payload),))
    feed, cohort = _strict_feed(store)
    try:
        feed.start()
        with pytest.raises(LiveCohortValidationError) as caught:
            feed._drain_live_ticks(limit=1)
        assert caught.value.code == "ACTION_DAY_INVALID"
        assert caught.value.report["field"] == "ActionDay"
        assert caught.value.report["category"] == "missing"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_action_day"
        latest = store.get_latest_tick_snapshot("rb2611")
        expected_action_day = None if delete_action_day else ""
        assert latest.ctp_raw_tick["ActionDay"] == expected_action_day
        assert latest.ctp_raw_tick["TradingDay"] == trading_day
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_volume_scope_and_rollback_preserve_the_last_good_baseline(monkeypatch):
    rows = (
        (7, _payload("09:30:05", 100)),
        (7, _payload("09:30:06", 103, millisec=1)),
        (7, _payload("09:30:07", 2, day="20261026", millisec=2)),
        (7, _payload("09:30:08", 5, day="20261026", millisec=3)),
        (8, _payload("09:30:09", 1, day="20261026", millisec=4)),
        (8, _payload("09:30:10", 5, day="20261026", millisec=5)),
        (8, _payload("09:30:11", 3, day="20261026", millisec=6)),
        (8, _payload("09:30:12", 7, day="20261026", millisec=7)),
        (8, _payload("09:30:12", 7, day="20261026", millisec=7)),
        (8, _payload("09:30:11", 8, day="20261026", millisec=8)),
        (8, _payload("09:30:13", 10, day="20261026", millisec=9)),
    )
    store = _store(monkeypatch, rows)
    try:
        store.start()
        events = tuple(store.poll_tick("rb2611") for _ in rows)
        assert [event.volume for event in events] == [
            0.0,
            3.0,
            0.0,
            3.0,
            0.0,
            4.0,
            0.0,
            2.0,
            0.0,
            0.0,
            3.0,
        ]
        assert events[6].ctp_raw_tick["volume_issue"] == "cumulative_volume_rollback"
        assert events[8].volume == 0.0  # an identical snapshot cannot add volume
        assert events[8].ctp_raw_tick["volume_issue"] is None
        assert events[9].ctp_raw_tick["volume_issue"] == "out_of_order"
        assert events[10].source == store.registered_sim_tick_source
    finally:
        store.stop()


@pytest.mark.integration
def test_registered_sim_discards_the_first_partial_minute_bucket(monkeypatch):
    from backtrader.feeds.btapifeed import BtApiFeed

    rows = (
        (7, _payload("09:30:05", 100)),
        (7, _payload("09:30:20", 104, millisec=1)),
        (7, _payload("09:31:05", 107, millisec=2)),
        (7, _payload("09:31:15", 109, millisec=3)),
        (7, _payload("09:32:05", 112, millisec=4)),
    )
    store = _store(monkeypatch, rows)
    feed = BtApiFeed(
        dataname="rb2611",
        store=store,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
    )
    try:
        feed.start()
        api = store._api
        assert api is not None
        assert type(api).__mro__[1].__name__ == "RegisteredSimWrapper"
        assert [event.volume for event in api._tick_queues["rb2611"]] == [
            0.0,
            4.0,
            3.0,
            2.0,
            3.0,
        ]
        while feed._drain_live_ticks(stop_after_queued_bar=False):
            pass
        bars = tuple(feed._live)
        assert len(bars) == 1
        # Backtrader line queues use UTC-naive datetimes internally.
        assert bars[0]["datetime"] == datetime(2026, 10, 23, 1, 31)
        assert bars[0]["volume"] == 5.0
    finally:
        store.stop()
