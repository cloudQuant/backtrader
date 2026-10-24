"""Synthetic CTP overnight ticks aggregate on planned UTC minutes."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.stores.registered_sim import RegisteredSimStore
from tests.unit.feeds import test_futures_sessions as sessions


_UTC = timezone.utc
_CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
_SYMBOL = "INE.SC2611"
_TRADING_DAY = "20261022"


class _GenerationMdClient:
    """Fake SDK leaf with the production generation-aware callback surface."""

    def __init__(self, **_kwargs):
        self._state_lock = threading.RLock()
        self._connection_generation = 1
        self.on_tick = None
        self.on_tick_with_generation = None
        self.on_disconnect = None
        self.on_disconnect_with_generation = None
        self.on_error = None

    @property
    def connection_generation(self):
        with self._state_lock:
            return self._connection_generation

    def start(self, block=False):
        assert block is False

    def wait_ready(self, timeout=20):
        return True

    def subscribe(self, _instruments):
        return None

    def capture_tick_callback(self, payload):
        """Capture callback and generation together under the SDK leaf lock."""
        with self._state_lock:
            callback = self.on_tick_with_generation
            generation = self._connection_generation
        assert callable(callback)
        return lambda: callback(payload, generation)

    def dispatch_tick(self, payload):
        self.capture_tick_callback(payload)()

    def disconnect(self):
        with self._state_lock:
            callback = self.on_disconnect_with_generation
            generation = self._connection_generation
        assert callable(callback)
        callback("synthetic_front_disconnect", generation)

    def reconnect(self, generation):
        with self._state_lock:
            assert generation > self._connection_generation
            self._connection_generation = generation

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


def _store(monkeypatch):
    ctp_client = pytest.importorskip("bt_api_ctp.ctp.client")
    monkeypatch.setattr(ctp_client, "MdClient", _GenerationMdClient)
    monkeypatch.setattr(ctp_client, "TraderClient", _FakeTraderClient)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID", raising=False)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_SECRET", raising=False)
    return RegisteredSimStore(
        provider="ctp",
        backend="direct",
        preserve_raw_bars=True,
        broker_id="synthetic-broker",
        user_id="synthetic-user",
        investor_id="synthetic-user",
        password="synthetic-password",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        auto_settlement_confirm=False,
    )


def _ctp_tick(local_time, cumulative_volume, price):
    return SimpleNamespace(
        InstrumentID="SC2611",
        ExchangeID="INE",
        LastPrice=price,
        Volume=cumulative_volume,
        BidPrice1=price - 0.2,
        AskPrice1=price + 0.2,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay=_TRADING_DAY,
        ActionDay=local_time.strftime("%Y%m%d"),
        UpdateTime=local_time.strftime("%H:%M:%S"),
        UpdateMillisec=local_time.microsecond // 1000,
    )


def _planned_night_closes():
    product = sessions.PRODUCTS[1]  # INE.SC, the existing 21:00–02:30 fixture.
    calendar = sessions._six_exchange_calendars()[1]
    grid = sessions.build_common_minute_grid(
        (product,),
        (calendar,),
        sessions._product_days((product,)),
        decision_at=sessions.DECISION_AT,
    )
    by_close = {minute.close_time: minute for minute in grid.minutes}
    first_close = datetime(2026, 10, 21, 16, 1, tzinfo=_UTC)
    second_close = datetime(2026, 10, 21, 16, 3, tzinfo=_UTC)
    return by_close[first_close], by_close[second_close]


@pytest.mark.integration
def test_ctp_overnight_action_day_trading_day_volume_and_generation_flow(monkeypatch):
    first_slot, second_slot = _planned_night_closes()
    first_member = first_slot.members[0]
    second_member = second_slot.members[0]
    assert first_member.session_date == date(2026, 10, 21)
    assert first_member.action_day == date(2026, 10, 22)
    assert first_member.trading_day == date(2026, 10, 22)
    assert second_member.action_day == date(2026, 10, 22)
    assert second_member.trading_day == date(2026, 10, 22)

    store = _store(monkeypatch)
    feed = bt.feeds.BtApiFeed(
        dataname=_SYMBOL,
        store=store,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
    )
    try:
        feed._start()
        api = store._api
        md_client = api.md_client
        assert type(api).__mro__[1].__name__ == "RegisteredSimWrapper"
        assert api._get_live_ctp_stream_health()["generation_callbacks_supported"] is True

        def load_tick(local_text, cumulative, price):
            local_time = datetime.fromisoformat(local_text).replace(tzinfo=_CHINA)
            md_client.dispatch_tick(_ctp_tick(local_time, cumulative, price))
            return feed.load()

        # The first observed bucket is a partial-volume baseline. Its source
        # ActionDay differs from the continuing exchange TradingDay.
        assert load_tick("2026-10-21T23:59:05", 1000, 100.0) is None
        assert load_tick("2026-10-21T23:59:35", 1030, 100.5) is None
        assert load_tick("2026-10-22T00:00:05", 1036, 101.0) is None
        assert load_tick("2026-10-22T00:00:35", 1041, 102.0) is None
        assert feed.load() is None
        first_line_loaded = load_tick("2026-10-22T00:01:05", 1042, 101.5)
        assert first_line_loaded is True

        first_line_time = bt.num2date(feed.datetime[0]).replace(microsecond=0)
        first_bucket_start = first_slot.close_time - timedelta(minutes=1)
        assert first_line_time == first_bucket_start.replace(tzinfo=None)
        assert feed.volume[0] == 11.0
        assert feed.open[0] == 101.0
        assert feed.high[0] == 102.0
        assert feed.low[0] == 101.0
        assert feed.close[0] == 102.0
        assert api._last_total_volume[("SC2611", _TRADING_DAY, 1)][1] == 1042.0

        # Capture an old-generation callback before disconnect. The callback
        # remains bound to generation 1 even when invoked after reconnection.
        delayed_old_tick = md_client.capture_tick_callback(
            _ctp_tick(datetime(2026, 10, 22, 0, 1, 20, tzinfo=_CHINA), 1090, 103.0)
        )
        md_client.disconnect()
        md_client.reconnect(2)
        delayed_old_tick()
        assert not api._tick_queues.get(_SYMBOL)

        # Generation 2 starts from a fresh cumulative-volume baseline. The
        # first partial minute is excluded; the next minute's deltas form a
        # real bar without inheriting generation 1's cumulative total.
        assert load_tick("2026-10-22T00:01:20", 5, 102.0) is None
        health = api._get_live_ctp_stream_health()
        assert health["source_generation"] == 2
        assert health["stale"] is False
        assert load_tick("2026-10-22T00:02:05", 12, 102.0) is None
        assert load_tick("2026-10-22T00:02:35", 15, 102.5) is None
        second_line_loaded = load_tick("2026-10-22T00:03:05", 17, 103.0)
        assert second_line_loaded is True

        second_line_time = bt.num2date(feed.datetime[0]).replace(microsecond=0)
        previous_line_time = bt.num2date(feed.datetime[-1]).replace(microsecond=0)
        second_bucket_start = second_slot.close_time - timedelta(minutes=1)
        assert previous_line_time == first_bucket_start.replace(tzinfo=None)
        assert second_line_time == second_bucket_start.replace(tzinfo=None)
        assert feed.volume[0] == 10.0
        assert feed.open[0] == 102.0
        assert feed.high[0] == 102.5
        assert feed.low[0] == 102.0
        assert feed.close[0] == 102.5
        assert api._last_total_volume[("SC2611", _TRADING_DAY, 2)][1] == 17.0
        assert api._get_live_ctp_stream_health()["source_generation"] == 2
    finally:
        feed.stop()
        store.stop()
