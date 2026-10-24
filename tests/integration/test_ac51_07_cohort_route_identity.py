"""Registered CTP aggregation keeps exact cohort route identity separate from display names."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import time
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
ROUTE = "A2612"
DISPLAY_NAME = "DCE.A"


class _Clock:
    def utc_now(self):
        return datetime(2026, 10, 23, 1, 33, tzinfo=UTC)

    def monotonic_ns(self):
        return time.monotonic_ns() + 1_000_000_000

    def wait(self, _timeout):
        return None


def _payload(time_text, volume, *, millisec=0):
    return SimpleNamespace(
        InstrumentID=ROUTE,
        ExchangeID="DCE",
        LastPrice=100.0,
        Volume=volume,
        BidPrice1=99.0,
        AskPrice1=101.0,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay="20261023",
        ActionDay="20261023",
        UpdateTime=time_text,
        UpdateMillisec=millisec,
    )


def _store(monkeypatch):
    ctp_client = pytest.importorskip("bt_api_ctp.ctp.client")
    rows = (
        _payload("09:30:05", 100),
        _payload("09:31:05", 104, millisec=1),
        _payload("09:31:20", 107, millisec=2),
        _payload("09:32:05", 110, millisec=3),
    )

    class _FakeMdClient:
        def __init__(self, **_kwargs):
            self.on_tick = None
            self.on_error = None
            self._connection_generation = 0
            self.payloads = rows

        def start(self, block=False):
            assert block is False
            for payload in self.payloads:
                self._connection_generation = 7
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
        live_tick_provenance={
            "source": "cohort-identity-fixture",
            "clock_domain_id": "cohort-identity-clock",
            "generation": 7,
            "rules_hash": "cohort-identity-rules-v1",
            "session_segment": "day",
        },
    )


def _cohort(feed):
    close_time = datetime(2026, 10, 23, 1, 32, tzinfo=UTC)
    calendar = LiveCohortCalendar(
        calendar_id="cohort-identity-calendar",
        version="fixture-v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="cohort-identity-clock",
        session_semantics="cohort-identity-session-v1",
        slots=(
            LiveCalendarSlot(
                slot_id="slot-0",
                bucket_start=close_time - timedelta(minutes=1),
                close_time=close_time,
                trading_day="20261023",
                session_segment="day",
                member_sessions={"member-A": LiveCalendarMemberSession("20261023", "day")},
            ),
        ),
    )
    cohort = LiveBarCohort(
        "cohort-identity",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=1_000_000_000,
    )
    cohort.register_member(
        "member-A",
        feed,
        instrument=ROUTE,
        source_ref="registered-sim-A2612",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    cohort.seal()
    return cohort


@pytest.mark.integration
def test_registered_sim_aggregate_uses_exact_route_for_cohort_and_keeps_display_evidence(
    monkeypatch,
):
    store = _store(monkeypatch)
    clock = _Clock()
    feed = bt.feeds.BtApiFeed(
        dataname=ROUTE,
        store=store,
        cohort_source_mode=True,
        backfill_start=False,
        historical_bars=(),
        live_bars=(),
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        closed_bar_quote_capture=True,
        clock=clock,
    )
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    cerebro.adddata(feed, name=DISPLAY_NAME)
    assert feed._name == DISPLAY_NAME

    cohort = _cohort(feed)
    feed._commit_live_bar_cohort_activation(feed._prepare_live_bar_cohort_activation(cohort, clock))
    try:
        feed.start()
        api = store._api
        assert api is not None
        assert type(api).__mro__[1].__name__ == "RegisteredSimWrapper"

        # The Store's real CTP conversion and Feed aggregation consume all four
        # cumulative snapshots, including the initial baseline and watermark tick.
        assert feed._drain_live_ticks() is True
        bar_event = feed._cohort_completed_lookahead
        assert bar_event is not None
        assert bar_event.symbol == ROUTE
        assert bar_event.bar_id.startswith(f"{ROUTE}:")
        assert bar_event.decision_version == bar_event.bar_id
        assert tuple(row["symbol"] for row in bar_event.quote_events) == (
            DISPLAY_NAME,
            DISPLAY_NAME,
        )

        # Capture uses the normal Feed→cohort source path and validates that the
        # exact route is the registered member instrument.
        assert feed._cohort_collect_source(clock.monotonic_ns()) == 1
        prepared = cohort.prepare_round(clock.monotonic_ns(), source_time_utc=clock.utc_now())
        assert prepared.status == "READY"
        envelope = prepared.prepared.envelopes["member-A"]
        assert envelope.instrument == ROUTE
        assert envelope.bar_id == bar_event.bar_id

        wrong_route_event = copy.copy(bar_event)
        wrong_route_event.symbol = "A2613"
        with pytest.raises(LiveCohortValidationError, match="exact feed member"):
            cohort.capture_bar(
                feed,
                wrong_route_event,
                source_role="live",
                received_monotonic_ns=clock.monotonic_ns(),
            )
    finally:
        feed.stop()
        store.stop()
