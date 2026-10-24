"""Raw CTP cold start through Alpha003 readiness and ordinary BackBroker."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live import LiveFactorSet
from backtrader.research.live_cohort import LiveBarCohort
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_live_alpha003_parity as parity


_UTC = timezone.utc
_TARGETS = ("rb2611", "hc2611", "i2611")
_BAR_COUNT = 32
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class _ColdStartStrategy(bt.Strategy):
    """Ordinary Strategy that buys only after the shared snapshot is ready."""

    params = (("cohort", None), ("plan", None))

    def __init__(self):
        feeds = {data._name: data for data in self.datas}
        self.live_factor_set = LiveFactorSet.bind(self.p.plan, feeds, cohort=self.p.cohort)
        self.snapshots = []
        self.buy_entries = []
        self.order_updates = []
        self.last_snapshot = None
        self.order = None

    def prenext(self):
        self._evaluate_batch()

    def nextstart(self):
        self._evaluate_batch()

    def next(self):
        self._evaluate_batch()

    def buy(self, *args, **kwargs):
        self.buy_entries.append(self.last_snapshot)
        return super().buy(*args, **kwargs)

    def notify_order(self, order):
        self.order_updates.append(order.getstatusname())

    def _evaluate_batch(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factor_set.snapshot()
        assert snapshot.batch_id == batch.batch_id
        assert snapshot.close_time == batch.close_time
        assert snapshot.batch_complete is True
        assert len({len(data) for data in self.datas}) == 1
        self.last_snapshot = snapshot
        self.snapshots.append(snapshot)

        if snapshot.readiness is LiveFactorReadiness.LIVE_READY and self.order is None:
            outputs = snapshot.factors["alpha003"].values
            assert set(outputs) == set(self.p.plan.targets)
            self.order = self.buy(data=self.datas[0], size=1)


class _ReplayClock(parity._ReplayClock):
    """Advance to raw source arrivals and wake the real Cerebro loop."""

    def __init__(self, now):
        super().__init__(now)
        self.source = None

    def wait(self, timeout_seconds):
        timeout = max(0.0, float(timeout_seconds))
        deadline = self.now + timedelta(seconds=timeout)
        next_event = None if self.source is None else self.source.next_event_time
        if next_event is not None and next_event <= deadline:
            target = max(self.now, next_event)
            elapsed = max(0.0, (target - self.now).total_seconds())
            self.now = target
            self._monotonic_ns += max(1, int(elapsed * 1_000_000_000))
            self.waits.append(elapsed)
            self.source.emit_until(target)
            return

        self.now = deadline
        self._monotonic_ns += max(1, int(timeout * 1_000_000_000))
        self.waits.append(timeout)


_CTP_TZ = timezone(timedelta(hours=8))


def _ctp_tick(instrument, exchange, minute_of_day, second, cumulative, price, millisec):
    hour = 9 + minute_of_day // 60
    minute = minute_of_day % 60
    source_time = datetime(2026, 10, 23, hour, minute, second, tzinfo=_CTP_TZ).astimezone(_UTC)
    payload = SimpleNamespace(
        InstrumentID=instrument,
        ExchangeID=exchange,
        LastPrice=price,
        Volume=cumulative,
        BidPrice1=price - 0.2,
        AskPrice1=price + 0.2,
        BidVolume1=2,
        AskVolume1=3,
        OpenInterest=1000,
        Turnover=0.0,
        TradingDay="20261023",
        ActionDay="20261023",
        UpdateTime="%02d:%02d:%02d" % (hour, minute, second),
        UpdateMillisec=millisec,
    )
    return payload, source_time


def _ticks():
    """Build source ticks with a high-volume first partial bucket per route."""
    exchange_by_target = {"rb2611": "SHFE", "hc2611": "SHFE", "i2611": "DCE"}
    totals = dict.fromkeys(_TARGETS, 1000)
    frames = tuple(parity._minute_frames(320).values())[: len(_TARGETS)]
    rows = []
    for asset_index, target in enumerate(_TARGETS):
        payload, source_time = _ctp_tick(
            target, exchange_by_target[target], 30, 5, totals[target], 100.0, 0
        )
        rows.append((source_time, target, 7, payload))
        totals[target] += 50
        payload, source_time = _ctp_tick(
            target, exchange_by_target[target], 30, 35, totals[target], 100.2, 1
        )
        rows.append((source_time, target, 7, payload))

    first_complete_volumes = {}
    for row_index in range(_BAR_COUNT):
        minute = 31 + row_index
        for asset_index, target in enumerate(_TARGETS):
            frame = frames[asset_index]
            volume_total = max(2, int(round(float(frame.iloc[row_index]["volume"]))))
            volume_a = volume_total // 2
            volume_b = volume_total - volume_a
            if row_index == 0:
                first_complete_volumes[target] = float(volume_total)
            price_a = float(frame.iloc[row_index]["open"])
            price_b = float(frame.iloc[row_index]["close"])
            totals[target] += volume_a
            payload, source_time = _ctp_tick(
                target,
                exchange_by_target[target],
                minute,
                5,
                totals[target],
                price_a,
                2,
            )
            rows.append((source_time, target, 7, payload))
            totals[target] += volume_b
            payload, source_time = _ctp_tick(
                target,
                exchange_by_target[target],
                minute,
                35,
                totals[target],
                price_b,
                3,
            )
            rows.append((source_time, target, 7, payload))

    # This source-time tick enters the next bucket and closes the final planned
    # minute. The new bucket remains partial and is never delivered as a bar.
    minute = 31 + _BAR_COUNT
    for asset_index, target in enumerate(_TARGETS):
        totals[target] += 3 + asset_index
        payload, source_time = _ctp_tick(
            target,
            exchange_by_target[target],
            minute,
            5,
            totals[target],
            101.0 + asset_index,
            4,
        )
        rows.append((source_time, target, 7, payload))
    target_order = {target: index for index, target in enumerate(_TARGETS)}
    rows.sort(key=lambda row: (row[0], target_order[row[1]]))
    return tuple(rows), first_complete_volumes


def _store(monkeypatch, rows, clock):
    ctp_client = pytest.importorskip("bt_api_ctp.ctp.client")

    class _FakeMdClient:
        def __init__(self, **_kwargs):
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            self._state_lock = threading.RLock()
            self._connection_generation = 0
            self._rows = rows
            self._index = 0
            clock.source = self

        @property
        def connection_generation(self):
            with self._state_lock:
                return self._connection_generation

        @property
        def next_event_time(self):
            if self._index >= len(self._rows):
                return None
            return self._rows[self._index][0]

        def emit_until(self, utc_time):
            while self.next_event_time is not None and self.next_event_time <= utc_time:
                _event_time, _instrument, generation, payload = self._rows[self._index]
                self._index += 1
                # Mirror the SDK SPI boundary: capture the callback and its
                # source generation together, then invoke without the lock.
                with self._state_lock:
                    self._connection_generation = generation
                    callback = self.on_tick_with_generation
                    callback_generation = self._connection_generation
                if callable(callback):
                    callback(payload, callback_generation)
                else:
                    self.on_tick(payload)

        def start(self, block=False):
            assert block is False
            self.emit_until(clock.utc_now())

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
            "source": "ac50-07a-raw-cold-start-fixture",
            "clock_domain_id": "alpha003-replay-clock-v1",
            "generation": 7,
            "rules_hash": "ac50-07a-fixture-rules-v1",
            "session_segment": "regular",
        },
    )


@pytest.mark.integration
def test_raw_no_history_cold_start_waits_for_alpha003_live_readiness(monkeypatch):
    rows, first_complete_volumes = _ticks()
    targets = _TARGETS
    grid = pd.date_range("2026-10-23 01:32:00", periods=_BAR_COUNT, freq="min", tz="UTC")
    calendar, member_ids = parity._calendar(targets, grid)
    clock = _ReplayClock(datetime(2026, 10, 23, 1, 30, 5, tzinfo=_UTC))
    store = _store(monkeypatch, rows, clock)
    cohort = LiveBarCohort(
        "ac50-07a-raw-cold-start",
        calendar,
        max_pending_slots=2,
        max_window_bars=_BAR_COUNT,
        wait_timeout_ns=15_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    for target in targets:
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            store=store,
            historical_bars=(),
            live_bars=(),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[target] = feed
        cerebro.adddata(feed, name=target)

    for target in targets:
        cohort.register_member(
            member_ids[target],
            feeds[target],
            instrument=target,
            source_ref="registered-sim-" + target,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )
    cohort.seal()
    plan = parity._live_alpha003_plan(
        targets,
        calendar=calendar,
        mode="native",
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=cohort.max_window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=10.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(_ColdStartStrategy, cohort=cohort, plan=plan)
    cerebro.broker.setcash(100_000.0)
    assert isinstance(cerebro.broker, bt.brokers.BackBroker)

    try:
        strategy = cerebro.run()[0]
    finally:
        store.stop()

    assert all(feed._cohort_history_source == () for feed in feeds.values())
    assert all(feed.live_bar_cohort is cohort for feed in feeds.values())
    assert len(strategy.snapshots) == _BAR_COUNT, (
        len(strategy.snapshots),
        cohort.frozen_reason,
        cohort.current_batch(),
        tuple(
            (
                target,
                len(feed),
                feed._bar_sequence,
                feed._cohort_delivery_failed,
                tuple(feed._bar_builders),
            )
            for target, feed in feeds.items()
        ),
    )
    assert all(snapshot.batch_complete for snapshot in strategy.snapshots)
    assert all(snapshot.epoch_id == 1 for snapshot in strategy.snapshots)
    assert all(
        snapshot.close_time == point.to_pydatetime()
        for snapshot, point in zip(strategy.snapshots, grid)
    )

    first_ready_index = next(
        index
        for index, snapshot in enumerate(strategy.snapshots)
        if snapshot.readiness is LiveFactorReadiness.LIVE_READY
    )
    factor = strategy.live_factor_set.factor_instances["alpha003"]["default"]
    ready_outputs = strategy.snapshots[first_ready_index].factors["alpha003"].values
    assert all(
        output.status.value == "OUTPUT_AVAILABLE" for output in ready_outputs.values()
    ), tuple(
        (target, output.status.value, output.reason, output.value)
        for target, output in ready_outputs.items()
    )
    assert first_ready_index + 1 >= max(plan.warmup_min_bars, factor._minperiod)
    assert all(
        snapshot.readiness is LiveFactorReadiness.WARMUP
        for snapshot in strategy.snapshots[:first_ready_index]
    )
    assert all(
        snapshot.readiness is LiveFactorReadiness.LIVE_READY
        for snapshot in strategy.snapshots[first_ready_index:]
    )

    assert len(strategy.buy_entries) == 1
    assert strategy.buy_entries[0].batch_id == strategy.snapshots[first_ready_index].batch_id
    assert strategy.order is not None
    assert strategy.order.getstatusname() in {"Submitted", "Accepted", "Completed"}
    assert any(
        status in {"Submitted", "Accepted", "Completed"} for status in strategy.order_updates
    )

    for target, feed in feeds.items():
        receipts = cohort.complete_window_bars(feed, _FIELDS, _BAR_COUNT)
        assert len(receipts) == _BAR_COUNT
        assert [receipt.slot_index for receipt in receipts] == list(range(_BAR_COUNT))
        assert all(receipt.source_role == "live" for receipt in receipts)
        assert all(
            receipt.present and receipt.complete and receipt.quality == "GOOD"
            for receipt in receipts
        )
        # The planned tape begins at 09:31 local (01:31 UTC) bucket start.
        # The 09:30 partial bucket carried +50 volume, but only the first
        # completed 09:31 bucket's real per-tick deltas are admitted.
        assert receipts[0].envelope.bucket_start == datetime(2026, 10, 23, 1, 31, tzinfo=_UTC)
        assert receipts[0].close_time == grid[0].to_pydatetime()
        assert receipts[0].raw_values["volume"] == first_complete_volumes[target]
        assert receipts[0].line_values["volume"] == first_complete_volumes[target]

    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert len(batch.members) == len(targets)
