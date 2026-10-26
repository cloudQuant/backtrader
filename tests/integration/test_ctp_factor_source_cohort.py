"""Exercise the real CTP Store/Feed/cohort path with synthetic SDK leaves.

The fake clients below replace only the provider SDK boundary. CTP callback
generation capture, Store normalization and queueing, Feed source-time
validation, minute aggregation, and cohort capture all run through production
components. No native SDK, account, or provider connection is involved.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.events import BarEvent
from backtrader.feeds.ctp_factor_source import (
    CtpFactorSourceBinding,
    CtpFactorSourceCalendar,
    CtpFactorSourceError,
    parse_ctp_trading_day,
)
from backtrader.feeds.futures_sessions import build_common_minute_grid
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortFrozenError,
)
from backtrader.stores.btapistore import BtApiStoreError
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.unit.feeds import test_futures_sessions as session_fixtures


_UTC = timezone.utc
_TRADING_DAY = session_fixtures.TRADING_DAY
_CLOCK_DOMAIN = "synthetic-ctp-factor-clock-v1"
_NIGHT_SLOT_CLOSE = datetime(2026, 10, 21, 16, 1, tzinfo=_UTC)
_DAY_SLOT_CLOSE = datetime(2026, 10, 22, 2, 31, tzinfo=_UTC)
_MD_GENERATION = 17
_TRADER_GENERATION = 91
_AUTO = object()
_INSTRUMENTS = {
    "CU": "CU2611",
    "SC": "SC2611",
    "IF": "IF2610",
}


def _target_id(product):
    return "{}-{}".format(product.exchange_id, product.product_id)


def _install_fake_ctp_sdk(monkeypatch):
    """Install complete public SDK module leaves before the Store resolves CTP."""
    instances = {"md": [], "trader": []}

    class FakeMdClient:
        def __init__(self, **_kwargs):
            self._state_lock = threading.RLock()
            self._connection_generation = _MD_GENERATION
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            self.start_calls = []
            self.subscriptions = []
            self.stop_count = 0
            instances["md"].append(self)

        @property
        def connection_generation(self):
            with self._state_lock:
                return self._connection_generation

        def start(self, *, block, join_observer):
            self.start_calls.append((block, join_observer))
            assert block is False
            assert join_observer is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def subscribe(self, instruments):
            self.subscriptions.append(tuple(instruments))

        def capture_tick_callback(self, payload):
            """Capture the exact callback and generation as an SDK SPI would."""
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            assert callable(callback)
            return lambda: callback(payload, generation)

        def dispatch_tick(self, payload, generation=None):
            with self._state_lock:
                callback = self.on_tick_with_generation
                captured_generation = (
                    self._connection_generation if generation is None else generation
                )
            assert callable(callback)
            callback(payload, captured_generation)

        def reconnect(self, generation):
            with self._state_lock:
                self._connection_generation = generation

        def stop(self):
            self.stop_count += 1

    class FakeTraderClient:
        def __init__(self, **_kwargs):
            self.on_login = None
            self.on_order = None
            self.on_trade = None
            self.on_error = None
            self.is_ready = False
            self.is_read_only_ready = False
            self.is_trading_ready = False
            self._front_id = None
            self._session_id = None
            self._trading_day = None
            self._connection_generation = None
            self.start_calls = []
            self.order_writes = []
            self.stop_count = 0
            instances["trader"].append(self)

        def start(self, *, block, join_observer):
            self.start_calls.append((block, join_observer))
            assert block is False
            assert join_observer is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def get_session_state(self):
            return {
                "connected": True,
                "ready": self.is_ready,
                "auth_state": "unknown",
                "login_state": "unknown",
            }

        def login_read_only(self, trading_day):
            self._front_id = 4
            self._session_id = 7
            self._trading_day = trading_day
            self._connection_generation = _TRADER_GENERATION
            self.is_read_only_ready = True
            assert callable(self.on_login)
            self.on_login(SimpleNamespace(FrontID=4, SessionID=7))

        def stop(self):
            self.stop_count += 1

    package = types.ModuleType("bt_api_ctp")
    package.__path__ = []
    ctp_package = types.ModuleType("bt_api_ctp.ctp")
    ctp_package.__path__ = []
    client_module = types.ModuleType("bt_api_ctp.ctp.client")
    client_module.MdClient = FakeMdClient
    client_module.TraderClient = FakeTraderClient
    client_module._MdSpi = type("_MdSpi", (), {})
    client_module._TraderSpi = type("_TraderSpi", (), {})
    package.ctp = ctp_package
    ctp_package.client = client_module

    md_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_md_api")
    md_api_module.CThostFtdcMdSpi = type("CThostFtdcMdSpi", (), {})
    trader_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_trader_api")
    trader_api_module.CThostFtdcTraderSpi = type("CThostFtdcTraderSpi", (), {})
    structs_module = types.ModuleType("bt_api_ctp.ctp.ctp_structs_order")
    structs_module.CThostFtdcInputOrderActionField = type(
        "CThostFtdcInputOrderActionField", (), {}
    )
    structs_module.CThostFtdcInputOrderField = type("CThostFtdcInputOrderField", (), {})

    for module_name, module in (
        ("bt_api_ctp", package),
        ("bt_api_ctp.ctp", ctp_package),
        ("bt_api_ctp.ctp.client", client_module),
        ("bt_api_ctp.ctp.ctp_md_api", md_api_module),
        ("bt_api_ctp.ctp.ctp_trader_api", trader_api_module),
        ("bt_api_ctp.ctp.ctp_structs_order", structs_module),
    ):
        monkeypatch.setitem(sys.modules, module_name, module)
    return instances


def _selected_grid(products):
    calendars_by_exchange = {
        calendar.exchange_id: calendar
        for calendar in session_fixtures._six_exchange_calendars()
    }
    selected_calendars = {
        product.exchange_id: calendars_by_exchange[product.exchange_id]
        for product in products
    }
    return build_common_minute_grid(
        products,
        tuple(selected_calendars.values()),
        {product: (_TRADING_DAY,) for product in products},
        decision_at=session_fixtures.DECISION_AT,
    ), selected_calendars


def _system(
    monkeypatch,
    *,
    products,
    cohort_close,
    source_clock_utc_now=None,
    feed_products=None,
    feed_instrument_overrides=None,
    binding_instrument_overrides=None,
):
    """Build real Store, BtApiFeed, Cerebro, and cohort around fake SDK leaves."""
    clients = _install_fake_ctp_sdk(monkeypatch)
    store = RegisteredSimStore(
        provider="ctp",
        backend="direct",
        preserve_raw_bars=True,
        broker_id="synthetic-broker",
        user_id="synthetic-user",
        investor_id="synthetic-user",
        password="synthetic-test-only",
        md_front="tcp://127.0.0.1:10001",
        td_front="tcp://127.0.0.1:10002",
        auto_settlement_confirm=False,
        ctp_join_observer=False,
        # A nonempty synthetic value prevents the Store constructor from
        # consulting any ambient CTP authorization environment variable.
        execution_authorization_key_id="synthetic-key-id",
        execution_authorization_secret="synthetic-secret",
    )
    try:
        store.start()
        assert store.registered_sim_wait_ready(0) is True
        with pytest.raises(BtApiStoreError, match="CTP_FACTOR_TRADER_NOT_READY"):
            store.enable_ctp_factor_tick_source()

        api = store._api
        md_client = api.md_client
        trader_client = api.trader_client
        assert store.registered_sim_login_facts()["read_only_ready"] is False
        trader_client.login_read_only(_TRADING_DAY.strftime("%Y%m%d"))
        assert store.registered_sim_login_facts()["connection_generation"] == _TRADER_GENERATION
        md_generation = store.enable_ctp_factor_tick_source()
        assert type(md_generation) is int and md_generation == _MD_GENERATION
        assert md_generation != _TRADER_GENERATION
        assert api._ctp_factor_callback_sequence == 0
        assert not any(api._tick_queues.values())

        grid, session_calendars = _selected_grid(products)
        planned_minute = next(
            minute for minute in grid.minutes if minute.close_time == cohort_close
        )
        source_calendar = CtpFactorSourceCalendar.from_grid(
            grid, _CLOCK_DOMAIN, session_calendars
        )
        feed_products = tuple(products if feed_products is None else feed_products)
        feed_instrument_overrides = dict(feed_instrument_overrides or {})
        binding_instrument_overrides = dict(binding_instrument_overrides or {})
        planned_members = {member.product: member for member in planned_minute.members}
        member_ids = {product: _target_id(product) for product in feed_products}
        slot_sessions = {
            member_ids[product]: LiveCalendarMemberSession(
                planned_members[product].trading_day.strftime("%Y%m%d"),
                planned_members[product].session_id,
            )
            for product in feed_products
        }
        slot = LiveCalendarSlot(
            slot_id="slot-{}".format(cohort_close.isoformat()),
            bucket_start=cohort_close - timedelta(minutes=1),
            close_time=cohort_close,
            trading_day=planned_members[feed_products[0]].trading_day.strftime("%Y%m%d"),
            session_segment="common-minute",
            member_sessions=slot_sessions,
        )
        live_calendar = LiveCohortCalendar(
            calendar_id="synthetic-ctp-factor-calendar",
            version="fixture-v1",
            epoch_id=1,
            frequency="1min",
            frequency_seconds=60,
            timezone_id="Asia/Shanghai",
            clock_domain_id=_CLOCK_DOMAIN,
            session_semantics="selected-product-session-v1",
            slots=(slot,),
        )
        cohort = LiveBarCohort(
            "synthetic-ctp-factor-cohort",
            live_calendar,
            max_pending_slots=2,
            max_window_bars=8,
            wait_timeout_ns=60_000_000_000,
        )
        source_clock = SimpleNamespace(
            utc_now=lambda: (
                source_clock_utc_now
                if source_clock_utc_now is not None
                else cohort_close + timedelta(minutes=5)
            ),
            monotonic_ns=time.monotonic_ns,
            wait=lambda _timeout: False,
        )
        cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
        feeds = {}
        aliases = {}
        instruments = {}
        dispatches = {}
        bindings = {}
        for product in feed_products:
            instrument_id = feed_instrument_overrides.get(
                product, _INSTRUMENTS[product.product_id]
            )
            alias = "{}.{}".format(product.exchange_id, instrument_id)
            binding_instrument = binding_instrument_overrides.get(product, instrument_id)
            target_id = member_ids[product]
            binding = CtpFactorSourceBinding(
                calendar=source_calendar,
                target_id=target_id,
                product=product,
                instrument_id=binding_instrument,
                exchange_id=product.exchange_id,
                trader_trading_day=parse_ctp_trading_day(
                    trader_client._trading_day
                ),
                expected_md_generation=md_generation,
            )
            feed = bt.feeds.BtApiFeed(
                dataname=alias,
                store=store,
                backfill_start=False,
                cohort_source_mode=True,
                ctp_factor_source_binding=binding,
                historical_bars=(),
                live_bars=(),
                timeframe=bt.TimeFrame.Minutes,
                compression=1,
                bar_watermark_ms=0,
                price_tick=0.2,
                dispatch_ticks=True,
                clock=source_clock,
            )
            cohort.register_member(
                target_id,
                feed,
                instrument=alias,
                source_ref="synthetic://ctp-factor/{}".format(target_id),
                line_fields=("open", "high", "low", "close", "volume"),
                raw_fields=("open", "high", "low", "close", "volume"),
                clock_domain_id=_CLOCK_DOMAIN,
                timezone_id="Asia/Shanghai",
                session_semantics="selected-product-session-v1",
            )
            feeds[product] = feed
            aliases[product] = alias
            instruments[product] = instrument_id
            bindings[product] = binding
            dispatches[product] = []
            cerebro.adddata(feed)

            original_dispatch = feed._dispatch_event

            def capture_dispatch(
                channel_type,
                priority,
                event_data,
                *,
                _original=original_dispatch,
                _events=dispatches[product],
            ):
                result = _original(
                    channel_type=channel_type,
                    priority=priority,
                    event_data=event_data,
                )
                if channel_type == "tick":
                    _events.append(event_data)
                return result

            monkeypatch.setattr(feed, "_dispatch_event", capture_dispatch)

        cerebro.add_live_bar_cohort(cohort, clock=source_clock)
        cerebro._activate_live_bar_cohort()
        for feed in feeds.values():
            feed._start()

        return SimpleNamespace(
            clients=clients,
            store=store,
            api=api,
            md_client=md_client,
            trader_client=trader_client,
            md_generation=md_generation,
            grid=grid,
            session_calendars=session_calendars,
            source_calendar=source_calendar,
            planned_minute=planned_minute,
            slot=slot,
            cohort=cohort,
            cerebro=cerebro,
            feeds=feeds,
            aliases=aliases,
            instruments=instruments,
            bindings=bindings,
            dispatches=dispatches,
            feed_products=feed_products,
        )
    except Exception:
        store.stop()
        raise


def _close_system(system):
    for feed in system.feeds.values():
        feed.stop()
    system.store.stop()


def _emit_tick(
    system,
    product,
    local_time,
    cumulative_volume,
    price=100.0,
    *,
    exchange_id=None,
    instrument_id=None,
    trading_day="20261022",
    action_day=_AUTO,
    update_time=_AUTO,
    generation=None,
):
    local = datetime.fromisoformat(local_time)
    payload = SimpleNamespace(
        InstrumentID=instrument_id or system.instruments[product],
        ExchangeID=product.exchange_id if exchange_id is None else exchange_id,
        LastPrice=price,
        Volume=cumulative_volume,
        BidPrice1=price - 0.2,
        AskPrice1=price + 0.2,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay=trading_day,
        ActionDay=local.strftime("%Y%m%d") if action_day is _AUTO else action_day,
        UpdateTime=local.strftime("%H:%M:%S") if update_time is _AUTO else update_time,
        UpdateMillisec=0,
    )
    system.md_client.dispatch_tick(payload, generation=generation)
    return payload


def _drain(feed):
    return feed._drain_live_ticks(limit=32, stop_after_queued_bar=False)


@pytest.mark.integration
def test_registered_sim_ctp_callbacks_aggregate_two_product_overnight_cohort(monkeypatch):
    cu, sc = session_fixtures.PRODUCTS[:2]
    system = _system(
        monkeypatch,
        products=(cu, sc),
        cohort_close=_NIGHT_SLOT_CLOSE,
    )
    try:
        assert system.source_calendar.grid is system.grid
        assert all(binding.calendar is system.source_calendar for binding in system.bindings.values())
        assert system.md_generation != system.store.registered_sim_login_facts()["connection_generation"]

        rows = (
            ("2026-10-21T23:59:05", 1000, 100.0),
            ("2026-10-21T23:59:35", 1030, 100.2),
            ("2026-10-22T00:00:05", 1036, 100.4),
            ("2026-10-22T00:00:35", 1041, 100.6),
            ("2026-10-22T00:01:05", 1042, 100.8),
        )
        original_rows = {cu: [], sc: []}
        for local_time, total, price in rows:
            original_rows[cu].append(
                _emit_tick(
                    system,
                    cu,
                    local_time,
                    total,
                    price,
                    exchange_id="",
                )
            )
            original_rows[sc].append(_emit_tick(system, sc, local_time, total, price))

        for product in (cu, sc):
            assert _drain(system.feeds[product]) is True
            event = system.feeds[product]._cohort_completed_lookahead
            assert isinstance(event, BarEvent)
            assert event.bucket_end == _NIGHT_SLOT_CLOSE
            assert event.trading_day == "20261022"
            assert event.action_day == "20261022"
            assert event.session_segment == "night"
            assert event.quality == "GOOD"
            assert event.volume == 11.0
            assert (event.open, event.high, event.low, event.close) == (
                100.4,
                100.6,
                100.4,
                100.6,
            )
            assert system.feeds[product]._bar_sequence == 1

            dispatched = system.dispatches[product]
            assert len(dispatched) == 5
            for emitted, source in zip(dispatched, original_rows[product]):
                raw = emitted.ctp_raw_tick
                assert raw["InstrumentID"] == source.InstrumentID
                assert raw["ExchangeID"] == source.ExchangeID
                assert raw["TradingDay"] == source.TradingDay
                assert raw["ActionDay"] == source.ActionDay
                assert raw["UpdateTime"] == source.UpdateTime
                assert raw["UpdateMillisec"] == source.UpdateMillisec
                assert emitted.ctp_callback_generation_captured is True
                assert emitted.connection_generation == system.md_generation
                assert emitted.stream_generation == system.md_generation
                assert emitted.ctp_callback_sequence == emitted.ingest_seq == emitted.sequence
                assert emitted.ctp_callback_received_wall_time > 0
                assert emitted.ctp_callback_received_monotonic_ns > 0
                assert emitted.received_wall_time == emitted.ctp_callback_received_wall_time
                assert emitted.received_monotonic_ns == emitted.ctp_callback_received_monotonic_ns
            assert [event.ctp_callback_sequence for event in dispatched] == sorted(
                event.ctp_callback_sequence for event in dispatched
            )

        cu_tick = system.dispatches[cu][0]
        assert cu_tick.ctp_raw_tick["ExchangeID"] == ""
        assert cu_tick.exchange_id == "SHFE"
        assert cu_tick.exchange_id_source == "subscription_plan"
        sc_tick = system.dispatches[sc][0]
        assert sc_tick.ctp_raw_tick["ExchangeID"] == "INE"
        assert sc_tick.exchange_id == "INE"
        assert sc_tick.exchange_id_source == "ctp_native"

        first = system.feeds[cu]._cohort_completed_lookahead
        assert system.feeds[cu]._cohort_capture_source(
            first, "live", time.monotonic_ns(), 0
        ) is True
        waiting = system.cohort.prepare_round(
            time.monotonic_ns(), source_time_utc=system.slot.close_time + timedelta(minutes=3)
        )
        assert waiting.status == "WAITING"
        assert waiting.missing_member_ids == (_target_id(sc),)
        assert system.cohort.current_batch() is None

        second = system.feeds[sc]._cohort_completed_lookahead
        assert system.feeds[sc]._cohort_capture_source(
            second, "live", time.monotonic_ns(), 0
        ) is True
        ready = system.cohort.prepare_round(
            time.monotonic_ns(), source_time_utc=system.slot.close_time + timedelta(minutes=3)
        )
        assert ready.status == "READY"
        assert ready.prepared.close_time == _NIGHT_SLOT_CLOSE
        assert system.cohort.current_batch() is None
        assert system.trader_client.order_writes == []
        assert system.api._pending_orders == {}
    finally:
        _close_system(system)


@pytest.mark.integration
def test_valid_outside_common_minute_quote_does_not_break_later_planned_cohort(monkeypatch):
    cu, _sc, _dce, _czce, if_product = session_fixtures.PRODUCTS[:5]
    system = _system(
        monkeypatch,
        products=(cu, if_product),
        cohort_close=_DAY_SLOT_CLOSE,
    )
    try:
        _emit_tick(system, cu, "2026-10-22T10:14:05", 100, 100.0)
        _emit_tick(system, if_product, "2026-10-22T10:14:05", 100, 100.2)
        _emit_tick(system, if_product, "2026-10-22T10:16:05", 101, 100.2)
        assert _drain(system.feeds[cu]) is True
        assert _drain(system.feeds[if_product]) is True
        assert system.feeds[cu]._bar_sequence == 0
        assert system.feeds[if_product]._bar_sequence == 0
        assert system.feeds[cu]._bar_builders == {}
        assert system.feeds[if_product]._bar_builders == {}

        outside_quote = system.dispatches[if_product][1]
        assert outside_quote.event_time_utc == datetime(2026, 10, 22, 2, 16, 5, tzinfo=_UTC)
        assert outside_quote.clock_domain_id == _CLOCK_DOMAIN
        assert not hasattr(outside_quote, "session_segment")
        assert outside_quote.ctp_raw_tick["ActionDay"] == "20261022"
        assert outside_quote.ctp_callback_generation_captured is True
        assert system.cohort.frozen is False
        assert system.api._get_live_ctp_stream_health()["stale"] is False
        assert system.store.get_stream_health(system.aliases[if_product])["stale"] is False

        later_rows = (
            ("2026-10-22T10:30:05", 103, 100.4),
            ("2026-10-22T10:30:35", 106, 100.6),
            ("2026-10-22T10:31:05", 107, 100.8),
        )
        for local_time, total, price in later_rows:
            _emit_tick(system, cu, local_time, total, price)
            _emit_tick(system, if_product, local_time, total - 1, price)
        for product in (cu, if_product):
            assert _drain(system.feeds[product]) is True
            event = system.feeds[product]._cohort_completed_lookahead
            assert isinstance(event, BarEvent)
            assert event.bucket_end == _DAY_SLOT_CLOSE
            assert event.trading_day == "20261022"
            assert event.session_segment in {"day-am-2", "day-am"}
            assert event.quality == "GOOD"
        assert system.feeds[cu]._cohort_capture_source(
            system.feeds[cu]._cohort_completed_lookahead, "live", time.monotonic_ns(), 0
        ) is True
        assert system.feeds[if_product]._cohort_capture_source(
            system.feeds[if_product]._cohort_completed_lookahead,
            "live",
            time.monotonic_ns(),
            0,
        ) is True
        ready = system.cohort.prepare_round(
            time.monotonic_ns(), source_time_utc=_DAY_SLOT_CLOSE + timedelta(minutes=3)
        )
        assert ready.status == "READY"
        assert system.cohort.frozen is False
        assert system.api._get_live_ctp_stream_health()["stale"] is False
        assert system.trader_client.order_writes == []
    finally:
        _close_system(system)


@pytest.mark.integration
@pytest.mark.parametrize(
    "conflict_field",
    (None, "datetime", "timestamp"),
    ids=("valid-end-quote", "datetime-conflict", "timestamp-conflict"),
)
def test_exact_session_end_quote_only_checks_normalized_event_time(monkeypatch, conflict_field):
    cu, sc = session_fixtures.PRODUCTS[:2]
    system = _system(
        monkeypatch,
        products=(cu, sc),
        feed_products=(sc,),
        cohort_close=_NIGHT_SLOT_CLOSE,
        source_clock_utc_now=datetime(2026, 10, 21, 18, 35, tzinfo=_UTC),
    )
    raw_rows = []
    poll_tick = system.store.poll_tick

    def observe_poll(symbol):
        event = poll_tick(symbol)
        if event is not None:
            raw_rows.append(event)
            if conflict_field == "datetime":
                event.datetime += timedelta(seconds=1)
            elif conflict_field == "timestamp":
                event.timestamp += 1.0
        return event

    monkeypatch.setattr(system.store, "poll_tick", observe_poll)
    try:
        payload = _emit_tick(system, sc, "2026-10-22T02:30:00", 100, 100.2)
        if conflict_field is not None:
            with pytest.raises(CtpFactorSourceError) as caught:
                _drain(system.feeds[sc])
            assert caught.value.code == "CTP_FACTOR_SOURCE_TIME_CONFLICT"
            assert raw_rows[0].ctp_raw_tick["ActionDay"] == payload.ActionDay == "20261022"
            assert raw_rows[0].ctp_raw_tick["TradingDay"] == payload.TradingDay == "20261022"
            assert raw_rows[0].ctp_raw_tick["UpdateTime"] == payload.UpdateTime == "02:30:00"
            assert system.dispatches[sc] == []
            assert system.feeds[sc]._bar_sequence == 0
            assert system.feeds[sc]._bar_builders == {}
            assert system.cohort.frozen is True
        else:
            assert _drain(system.feeds[sc]) is True
            event = system.dispatches[sc][0]
            assert event.event_time_utc == datetime(2026, 10, 21, 18, 30, tzinfo=_UTC)
            assert event.clock_domain_id == _CLOCK_DOMAIN
            assert event.ctp_source_time_contract == "ctp-asia-shanghai-fixed-utc8-v1"
            assert event.exchange_id_source == "ctp_native"
            assert not hasattr(event, "session_segment")
            assert event.ctp_raw_tick["ActionDay"] == payload.ActionDay == "20261022"
            assert event.ctp_raw_tick["TradingDay"] == payload.TradingDay == "20261022"
            assert event.ctp_raw_tick["UpdateTime"] == payload.UpdateTime == "02:30:00"
            assert system.feeds[sc]._bar_sequence == 0
            assert system.feeds[sc]._bar_builders == {}
            assert system.cohort.frozen is False
            assert system.api._get_live_ctp_stream_health()["stale"] is False
        assert system.trader_client.order_writes == []
    finally:
        _close_system(system)


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalidity, expected_code",
    (
        ("missing-update-time", "CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID"),
        ("missing-action-day", "CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID"),
        ("missing-trading-day", "CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID"),
        ("wrong-instrument-binding", "CTP_FACTOR_SOURCE_ROUTE_MISMATCH"),
        ("conflicting-exchange", "CTP_FACTOR_SOURCE_ROUTE_MISMATCH"),
        ("unsupported-action-day", "CTP_FACTOR_SOURCE_SESSION_MISMATCH"),
    ),
    ids=(
        "missing-update-time",
        "missing-action-day",
        "missing-trading-day",
        "wrong-instrument-binding",
        "conflicting-exchange",
        "unsupported-action-day",
    ),
)
def test_malformed_or_wrong_route_ctp_callback_freezes_factor_source(
    monkeypatch, invalidity, expected_code
):
    cu = session_fixtures.PRODUCTS[0]
    binding_overrides = {cu: "CU2612"} if invalidity == "wrong-instrument-binding" else None
    system = _system(
        monkeypatch,
        products=(cu,),
        cohort_close=_DAY_SLOT_CLOSE,
        binding_instrument_overrides=binding_overrides,
    )
    try:
        if invalidity == "missing-update-time":
            kwargs = {"update_time": ""}
        elif invalidity == "missing-action-day":
            kwargs = {"action_day": None}
        elif invalidity == "missing-trading-day":
            kwargs = {"trading_day": None}
        elif invalidity == "conflicting-exchange":
            kwargs = {"exchange_id": "DCE"}
        elif invalidity == "unsupported-action-day":
            kwargs = {
                "action_day": "20261023",
                "update_time": "09:00:05",
            }
        else:
            kwargs = {}
        _emit_tick(
            system,
            cu,
            "2026-10-22T09:30:05",
            100,
            100.0,
            **kwargs,
        )
        with pytest.raises(CtpFactorSourceError) as caught:
            _drain(system.feeds[cu])
        assert caught.value.code == expected_code
        assert system.cohort.frozen is True
        assert system.api._ctp_factor_callback_sequence == 1
        assert system.dispatches[cu] == []
        assert system.feeds[cu]._bar_sequence == 0
        assert system.feeds[cu]._bar_builders == {}
        assert system.trader_client.order_writes == []
    finally:
        _close_system(system)


@pytest.mark.integration
def test_md_reconnect_generation_change_is_stale_before_new_generation_tick(monkeypatch):
    cu = session_fixtures.PRODUCTS[0]
    system = _system(
        monkeypatch,
        products=(cu,),
        cohort_close=_DAY_SLOT_CLOSE,
    )
    try:
        queued = _emit_tick(system, cu, "2026-10-22T09:30:05", 100, 100.0)
        delayed_old_callback = system.md_client.capture_tick_callback(
            _emit_callback_only(system, cu, "2026-10-22T09:30:35", 101, 100.2)
        )
        alias = system.aliases[cu]
        assert len(system.api._tick_queues[alias]) == 1
        assert system.api._tick_queues[alias][0].ctp_raw_tick["InstrumentID"] == queued.InstrumentID

        system.md_client.reconnect(_MD_GENERATION + 1)
        # The wrapper's actual connect-completion handler must retain stale
        # state immediately, before the reconnect sends any market callback.
        system.api._mark_md_client_connected(system.md_client)
        health = system.api._get_live_ctp_stream_health()
        assert health["stale"] is True
        assert health["stale_reason"] == "ctp_factor_md_generation_changed"
        assert health["source_generation"] == _MD_GENERATION
        assert len(system.api._tick_queues[alias]) == 0

        delayed_old_callback()
        assert len(system.api._tick_queues[alias]) == 0
        assert system.api._ctp_factor_callback_sequence == 1

        _emit_tick(
            system,
            cu,
            "2026-10-22T09:31:05",
            102,
            100.4,
            generation=_MD_GENERATION + 1,
        )
        assert len(system.api._tick_queues[alias]) == 0
        assert system.api._ctp_factor_callback_sequence == 1
        health = system.api._get_live_ctp_stream_health()
        assert health["stale"] is True
        assert health["stale_reason"] == "ctp_factor_md_generation_changed"
        with pytest.raises(LiveCohortFrozenError):
            _drain(system.feeds[cu])
        assert system.cohort.frozen is True
        assert system.trader_client.order_writes == []
    finally:
        _close_system(system)


def _emit_callback_only(system, product, local_time, cumulative_volume, price):
    local = datetime.fromisoformat(local_time)
    return SimpleNamespace(
        InstrumentID=system.instruments[product],
        ExchangeID=product.exchange_id,
        LastPrice=price,
        Volume=cumulative_volume,
        BidPrice1=price - 0.2,
        AskPrice1=price + 0.2,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay="20261022",
        ActionDay=local.strftime("%Y%m%d"),
        UpdateTime=local.strftime("%H:%M:%S"),
        UpdateMillisec=0,
    )
