"""Run the raw CTP source contract through ordinary Cerebro Alpha003 execution.

Only the provider SDK boundary and deterministic source clock are synthetic.
The registered Store callback, tick queue, BtApiFeed validation/aggregation,
cohort publication, Cerebro loop, and production Alpha003 graph remain real.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backtrader as bt
import backtrader.stores.btapistore as btapistore_module
import pandas as pd
import pytest

from backtrader.research.live import LiveFactorReadiness
from backtrader.feeds.ctp_factor_source import (
    CTP_FACTOR_SOURCE_TIME_CONTRACT,
    CtpFactorSourceBinding,
    CtpFactorSourceCalendar,
    parse_ctp_trading_day,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_ctp_factor_source_cohort as source_fixture
from tests.integration import test_live_alpha003_parity as parity
from tests.unit.feeds import test_futures_sessions as session_fixtures


_CTP_TZ = timezone(timedelta(hours=8))
_CLOCK_DOMAIN = "raw-ctp-alpha003-normal-cerebro-v1"
_BAR_COUNT = 50
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_PRODUCTS = tuple(session_fixtures.PRODUCTS[index] for index in (2, 3, 5))
_INSTRUMENTS = {"M": "M2611", "CF": "CF701", "SI": "SI2611"}
_TRADING_DAY = session_fixtures.TRADING_DAY


class _RawSourceClock:
    """Advance source UTC time and deliver raw callbacks only from Cerebro waits."""

    def __init__(self, events, *, now):
        self.now = now
        self.events = tuple(events)
        self.index = 0
        self.md_client = None
        self.md_generation = None
        self.emitted = 0
        self.wait_count = 0
        self.diagnostic = None
        self.cohort_is_frozen = None
        self.max_internal_eof_yields = 0
        self._internal_eof_yields = 0

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        # Callback receipt monotonic timestamps come from the real Store
        # boundary; keeping this clock on the same process clock avoids a
        # synthetic age jump while UTC follows the finite historical tape.
        return time.monotonic_ns()

    def wait(self, timeout_seconds):
        timeout = max(0.0, float(timeout_seconds))
        deadline = self.now + timedelta(seconds=timeout)
        self.wait_count += 1
        if self.index >= len(self.events):
            detail = self.diagnostic() if callable(self.diagnostic) else None
            if (
                callable(self.cohort_is_frozen)
                and not self.cohort_is_frozen()
                and self._internal_eof_yields < self.max_internal_eof_yields
            ):
                # Raw callback dispatch may finish before the bounded Store
                # tick queues and Feed bar builders drain. Retry only the
                # normal Cerebro poll, with unchanged UTC and no new callback.
                self._internal_eof_yields += 1
                return
            raise AssertionError("Cerebro stalled after finite raw CTP EOF: {!r}".format(detail))

        next_time = self.events[self.index][0]
        if next_time <= deadline:
            target = max(self.now, next_time)
            self.now = target
            while self.index < len(self.events) and self.events[self.index][0] <= target:
                event_time, payload = self.events[self.index]
                if event_time < self.now:
                    raise AssertionError("raw CTP event order moved behind the source clock")
                self.md_client.dispatch_tick(payload, generation=self.md_generation)
                self.index += 1
                self.emitted += 1
            self._internal_eof_yields = 0
            return

        self.now = deadline


class _SourceTimeProxy:
    """Bind Store callback wall time to the same synthetic source timeline."""

    def __init__(self, clock):
        self._clock = clock

    def time(self):
        return self._clock.utc_now().timestamp()

    def __getattr__(self, name):
        return getattr(time, name)


class _StopAfterRawCohort(parity._LiveAlpha003Capture):
    """Use the shared production-factor capture and stop after 50 real batches."""

    def _capture(self):
        super()._capture()
        if len(self.snapshots) == _BAR_COUNT:
            self.cerebro.runstop()


def _alpha003_frames(minutes):
    """Make three distinct cross-sectional rank paths from the public oracle fixture."""
    base = parity._minute_frames(320)
    base_assets = tuple(base)[: len(_PRODUCTS)]
    closes = pd.DatetimeIndex([minute.close_time for minute in minutes])
    aliases = tuple(
        "{}.{}".format(product.exchange_id, _INSTRUMENTS[product.product_id])
        for product in _PRODUCTS
    )
    open_ranks = {alias: [] for alias in aliases}
    volume_ranks = {alias: [] for alias in aliases}

    for row in range(_BAR_COUNT):
        open_order = sorted(
            base_assets,
            key=lambda asset: (float(base[asset].iloc[row]["open"]), asset),
        )
        volume_order = sorted(
            base_assets,
            key=lambda asset: (float(base[asset].iloc[row]["volume"]), asset),
        )
        open_rank_by_asset = {asset: rank for rank, asset in enumerate(open_order)}
        volume_rank_by_asset = {asset: rank for rank, asset in enumerate(volume_order)}
        for alias, asset in zip(aliases, base_assets):
            open_ranks[alias].append(open_rank_by_asset[asset])
            volume_ranks[alias].append(volume_rank_by_asset[asset])

    frames = {}
    for alias in aliases:
        opens = [100.0 + 0.2 * rank for rank in open_ranks[alias]]
        volumes = [10.0 + rank for rank in volume_ranks[alias]]
        frames[alias] = pd.DataFrame(
            {
                "open": opens,
                "high": [value + 0.2 for value in opens],
                "low": [value - 0.2 for value in opens],
                "close": opens,
                "volume": volumes,
                "openinterest": [1000.0] * _BAR_COUNT,
            },
            index=closes,
        )

    assert all(len(set(values)) > 1 for values in open_ranks.values())
    assert all(len(set(values)) > 1 for values in volume_ranks.values())
    assert all(
        len({frames[alias].iloc[row]["open"] for alias in aliases}) == 3
        for row in range(_BAR_COUNT)
    )
    assert all(
        len({frames[alias].iloc[row]["volume"] for alias in aliases}) == 3
        for row in range(_BAR_COUNT)
    )
    return frames, aliases


def _raw_tick(product, instrument, local_time, cumulative_volume, price):
    return SimpleNamespace(
        InstrumentID=instrument,
        ExchangeID=product.exchange_id,
        LastPrice=price,
        Volume=cumulative_volume,
        BidPrice1=price - 0.2,
        AskPrice1=price + 0.2,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay=_TRADING_DAY.strftime("%Y%m%d"),
        ActionDay=local_time.strftime("%Y%m%d"),
        UpdateTime=local_time.strftime("%H:%M:%S"),
        UpdateMillisec=0,
    )


def _events_for_frames(minutes, frames, aliases):
    events = []
    local_delta = timedelta(seconds=8 * 60 * 60)
    for product, alias in zip(_PRODUCTS, aliases):
        instrument = _INSTRUMENTS[product.product_id]
        cumulative = 1000
        frame = frames[alias]
        # Seed the real Store's cumulative-volume baseline in the selected
        # source minute before the first cohort bar. BtApiFeed deliberately
        # ignores that first partial bucket during normal CTP aggregation.
        seed_utc = minutes[0].close_time - timedelta(minutes=2) + timedelta(seconds=5)
        seed_local = (seed_utc + local_delta).replace(tzinfo=_CTP_TZ)
        events.append(
            (
                seed_utc,
                _raw_tick(
                    product,
                    instrument,
                    seed_local,
                    cumulative,
                    float(frame.iloc[0]["open"]),
                ),
            )
        )
        for row, minute in enumerate(minutes):
            bucket_start = minute.close_time - timedelta(minutes=1)
            price = float(frame.iloc[row]["open"])
            first_local = (bucket_start + timedelta(seconds=5) + local_delta).replace(
                tzinfo=_CTP_TZ
            )
            second_local = (bucket_start + timedelta(seconds=35) + local_delta).replace(
                tzinfo=_CTP_TZ
            )
            events.append(
                (
                    bucket_start + timedelta(seconds=5),
                    _raw_tick(product, instrument, first_local, cumulative, price),
                )
            )
            cumulative += int(frame.iloc[row]["volume"])
            events.append(
                (
                    bucket_start + timedelta(seconds=35),
                    _raw_tick(product, instrument, second_local, cumulative, price),
                )
            )

        # A first tick in the next bucket lets the real Feed close the final
        # planned minute; the partial next bucket is cleared by normal teardown.
        terminal_utc = minutes[-1].close_time + timedelta(seconds=5)
        terminal_local = (terminal_utc + local_delta).replace(tzinfo=_CTP_TZ)
        events.append(
            (
                terminal_utc,
                _raw_tick(
                    product,
                    instrument,
                    terminal_local,
                    cumulative,
                    float(frame.iloc[-1]["close"]),
                ),
            )
        )

    events.sort(key=lambda item: (item[0], item[1].InstrumentID))
    return tuple(events)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_registered_sim_raw_ctp_callbacks_reach_alpha003_through_cerebro(
    monkeypatch, request, mode
):
    """Exercise source callback through real Store/Feed/cohort/Alpha003 lifecycle."""
    clients = source_fixture._install_fake_ctp_sdk(monkeypatch)
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
        execution_authorization_key_id="synthetic-key-id",
        execution_authorization_secret="synthetic-secret",
    )
    request.addfinalizer(store.stop)
    store.start()
    assert store.registered_sim_wait_ready(0) is True
    api = store._api
    md_client = api.md_client
    trader_client = api.trader_client
    trader_client.login_read_only(_TRADING_DAY.strftime("%Y%m%d"))
    md_generation = store.enable_ctp_factor_tick_source()
    assert type(md_generation) is int and md_generation > 0
    assert md_generation == md_client.connection_generation
    assert md_generation != store.registered_sim_login_facts()["connection_generation"]
    assert api._ctp_factor_callback_sequence == 0

    grid, session_calendars = source_fixture._selected_grid(_PRODUCTS)
    # The first cumulative observation for each CTP stream is a source
    # baseline, so its partially observed minute is intentionally not a bar.
    # Leave that selected-grid slot before the 50 production factor slots.
    minutes = tuple(grid.minutes[1 : _BAR_COUNT + 1])
    assert len(minutes) == _BAR_COUNT
    frames, aliases = _alpha003_frames(minutes)
    events = _events_for_frames(minutes, frames, aliases)
    assert len(events) == len(_PRODUCTS) * (_BAR_COUNT * 2 + 2)
    clock = _RawSourceClock(events, now=events[0][0] - timedelta(seconds=1))
    clock.md_client = md_client
    clock.md_generation = md_generation
    # Raw callback EOF can precede draining the Store queues and Feed builders.
    # Allow a finite number of no-callback engine polls without advancing UTC.
    clock.max_internal_eof_yields = 64
    # The raw CTP event clock is historical and deterministic. Keep callback
    # wall receipts on that same timeline so Feed freshness compares the
    # source event with its actual synthetic callback receipt, while Store
    # monotonic receipt values continue to use the real process clock.
    monkeypatch.setattr(btapistore_module, "time", _SourceTimeProxy(clock))

    source_calendar = CtpFactorSourceCalendar.from_grid(
        grid, _CLOCK_DOMAIN, session_calendars
    )
    trading_day = parse_ctp_trading_day(_TRADING_DAY.strftime("%Y%m%d"))
    target_ids = {product: source_fixture._target_id(product) for product in _PRODUCTS}
    slots = []
    for index, minute in enumerate(minutes):
        members = {member.product: member for member in minute.members}
        assert set(members) == set(_PRODUCTS)
        sessions = {
            target_ids[product]: LiveCalendarMemberSession(
                trading_day=members[product].trading_day.strftime("%Y%m%d"),
                session_segment=members[product].session_id,
            )
            for product in _PRODUCTS
        }
        slots.append(
            LiveCalendarSlot(
                slot_id="raw-ctp-alpha003-slot-{}".format(index),
                bucket_start=minute.close_time - timedelta(minutes=1),
                close_time=minute.close_time,
                trading_day=members[_PRODUCTS[0]].trading_day.strftime("%Y%m%d"),
                session_segment="common-minute",
                member_sessions=sessions,
            )
        )

    calendar = LiveCohortCalendar(
        calendar_id="raw-ctp-alpha003-calendar-v1",
        version="synthetic-selected-grid-v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="Asia/Shanghai",
        clock_domain_id=_CLOCK_DOMAIN,
        session_semantics="selected-product-session-v1",
        slots=tuple(slots),
    )
    cohort = LiveBarCohort(
        "raw-ctp-alpha003-normal-cerebro",
        calendar,
        max_pending_slots=2,
        max_window_bars=_BAR_COUNT,
        wait_timeout_ns=60_000_000_000,
    )

    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    bindings = {}
    dispatched_ticks = {}
    product_for_alias = dict(zip(aliases, _PRODUCTS))
    for product, alias in zip(_PRODUCTS, aliases):
        target_id = target_ids[product]
        instrument = _INSTRUMENTS[product.product_id]
        binding = CtpFactorSourceBinding(
            calendar=source_calendar,
            target_id=target_id,
            product=product,
            instrument_id=instrument,
            exchange_id=product.exchange_id,
            trader_trading_day=trading_day,
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
            clock=clock,
        )
        cohort.register_member(
            target_id,
            feed,
            instrument=alias,
            source_ref="synthetic://raw-ctp-alpha003/{}".format(target_id),
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
            clock_domain_id=_CLOCK_DOMAIN,
            timezone_id="Asia/Shanghai",
            session_semantics="selected-product-session-v1",
        )
        feeds[alias] = feed
        bindings[alias] = binding
        dispatched_ticks[alias] = []
        original_dispatch = feed._dispatch_event

        def capture_tick_dispatch(
            channel_type,
            priority,
            event_data,
            *,
            _original=original_dispatch,
            _events=dispatched_ticks[alias],
        ):
            result = _original(
                channel_type=channel_type,
                priority=priority,
                event_data=event_data,
            )
            if channel_type == "tick":
                _events.append(event_data)
            return result

        monkeypatch.setattr(feed, "_dispatch_event", capture_tick_dispatch)
        cerebro.adddata(feed, name=alias)

    plan = parity._live_alpha003_plan(
        aliases,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=cohort.max_window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=10.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _StopAfterRawCohort,
        cohort=cohort,
        plan=plan,
        target_order=aliases,
    )
    assert isinstance(cerebro.broker, bt.brokers.BackBroker)
    clock.cohort_is_frozen = lambda: cohort.frozen
    clock.diagnostic = lambda: {
        "emitted": clock.emitted,
        "source_events": len(events),
        "utc_now": clock.now.isoformat(),
        "internal_eof_yields": clock._internal_eof_yields,
        "max_internal_eof_yields": clock.max_internal_eof_yields,
        "cohort_frozen": cohort.frozen,
        "cohort_frozen_reason": cohort.frozen_reason,
        "current_batch": None
        if cohort.current_batch() is None
        else {
            "status": cohort.current_batch().status,
            "slot_index": cohort.current_batch().slot_index,
            "close_time": cohort.current_batch().close_time.isoformat(),
        },
        "feeds": {
            alias: {
                "len": len(feed),
                "bar_sequence": feed._bar_sequence,
                "builders": len(feed._bar_builders),
                "completed_lookahead": feed._cohort_completed_lookahead is not None,
                "delivery_failed": feed._cohort_delivery_failed,
                "history_source_exhausted": feed._cohort_source_is_exhausted(),
            }
            for alias, feed in feeds.items()
        },
    }

    strategy = cerebro.run()[0]

    assert len(strategy.snapshots) == _BAR_COUNT
    assert all(snapshot.batch_complete for snapshot in strategy.snapshots)
    assert all(
        snapshot.readiness is LiveFactorReadiness.WARMUP
        for snapshot in strategy.snapshots[: parity._WARMUP_BARS - 1]
    )
    assert all(
        snapshot.readiness is LiveFactorReadiness.LIVE_READY
        for snapshot in strategy.snapshots[parity._WARMUP_BARS - 1 :]
    )
    assert len({snapshot.batch_id for snapshot in strategy.snapshots}) == _BAR_COUNT
    assert cohort.current_batch().status == "COMPLETE"
    assert cohort.current_batch().slot_index == _BAR_COUNT - 1
    assert tuple(snapshot.close_time for snapshot in strategy.snapshots) == tuple(
        minute.close_time for minute in minutes
    )
    assert clock.emitted == len(events)
    assert clock.index == len(events)
    assert api._ctp_factor_callback_sequence == len(events)
    assert api._get_live_ctp_stream_health()["stale"] is False
    assert trader_client.order_writes == []
    assert api._pending_orders == {}

    for alias, feed in feeds.items():
        assert feed._bar_sequence == _BAR_COUNT
        assert feed._bar_builders == {}
        assert feed._cohort_delivery_failed is False
        assert feed._ctp_factor_source_binding is bindings[alias]
        ticks = dispatched_ticks[alias]
        assert len(ticks) == _BAR_COUNT * 2 + 2
        assert all(tick.ctp_callback_generation_captured is True for tick in ticks)
        assert all(tick.connection_generation == md_generation for tick in ticks)
        assert all(tick.clock_domain_id == _CLOCK_DOMAIN for tick in ticks)
        assert all(
            tick.ctp_source_time_contract == CTP_FACTOR_SOURCE_TIME_CONTRACT for tick in ticks
        )
        assert all(
            tick.ctp_raw_tick["InstrumentID"]
            == _INSTRUMENTS[product_for_alias[alias].product_id]
            and tick.ctp_raw_tick["ExchangeID"] == bindings[alias].exchange_id
            for tick in ticks
        )
        assert all(
            tick.ctp_callback_sequence == tick.ingest_seq == tick.sequence for tick in ticks
        )
        health = store.get_stream_health(alias)
        assert health["stale"] is False
        receipts = cohort.complete_window_bars(feed, _FIELDS, _BAR_COUNT)
        assert len(receipts) == _BAR_COUNT
        assert all(
            receipt.source_role == "live"
            and receipt.present is True
            and receipt.complete is True
            and receipt.quality == "GOOD"
            for receipt in receipts
        )
        assert [receipt.raw_values["open"] for receipt in receipts] == list(
            frames[alias]["open"]
        )
        assert [receipt.raw_values["volume"] for receipt in receipts] == list(
            frames[alias]["volume"]
        )

    expected, factor = parity._validate_live(
        strategy,
        frames,
        label="raw registered CTP Alpha003 {}".format(mode),
    )
    assert factor.factor_mode == mode
    finite_values = [
        float(value)
        for row in expected
        for value in row
        if math.isfinite(float(value))
    ]
    assert len(finite_values) >= 100
    assert len({round(value, 10) for value in finite_values}) > 1
    store.stop()
    shutdown = store.get_command_health()["ctp_factor_source_shutdown"]
    assert shutdown["required"] is True
    assert shutdown["status"] == "PASS"
    assert shutdown["expected_md_generation"] == md_generation
    assert shutdown["expected_trader_generation"] == trader_client.get_session_state()[
        "connection_generation"
    ]
    assert shutdown["join_required"] is False
    assert shutdown["reason_codes"] == ()
    for name, client, receipt in (
        ("md", md_client, shutdown["md_receipt"]),
        ("trader", trader_client, shutdown["trader_receipt"]),
    ):
        assert client.stop_count == 1
        assert client.stop_wait_count == 1
        assert receipt == {
            "connection_generation": shutdown[
                "expected_{}_generation".format(name)
            ],
            "join_required": False,
            "join_completed": True,
            "native_released": True,
            "thread_alive": False,
            "timed_out": False,
            "complete": True,
        }
