"""One normal pending wait exercises live-factor and ordinary broker progress."""

from __future__ import annotations

from copy import deepcopy
import threading
from types import MappingProxyType

import backtrader as bt

from backtrader.research import FactorSpec, LiveFactorPlan
from backtrader.research.live_cohort import LiveBarCohort
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store
from tests.integration.test_live_factor_cohort_composition import (
    CohortClose,
    CohortStrategy,
    _FACTOR_ADVANCES,
    _bar_event,
    _calendar,
)


class _DelayedEventClient(FakeBtApiClient):
    """Publish one later Store bar and wake Cerebro through the Store API."""

    def __init__(self, *, live):
        super().__init__(live=live)
        self._event_notifier = None
        self.notifier_bound = threading.Event()
        self.publish_count = 0
        self._notifier_lock = threading.Lock()

    def set_live_bar_event_notifier(self, callback):
        with self._notifier_lock:
            self._event_notifier = callback
            if callback is not None:
                self.notifier_bound.set()

    def publish_bar(self, symbol, event):
        self.live.setdefault(symbol, []).append(deepcopy(dict(event)))
        with self._notifier_lock:
            notifier = self._event_notifier
        if not callable(notifier):
            raise AssertionError("the production Store event notifier was not registered")
        self.publish_count += 1
        notifier()


class _InterruptibleClock:
    """Fixed source-time clock that delegates its real event wait to Cerebro."""

    def __init__(self, now):
        self.now = now
        self.monotonic = 1_000
        self.wait_started = threading.Event()
        self.wait_results = []
        self.wait_timeouts = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        raise AssertionError("the registered Store should use the interruptible wait")

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        self.wait_timeouts.append(timeout_seconds)
        self.wait_started.set()
        interrupted = wait_for_event(timeout_seconds)
        self.wait_results.append(interrupted)
        return interrupted


class _PendingWaitStrategy(CohortStrategy):
    """Submit after a real complete batch and stop after the delayed next one."""

    def __init__(self):
        super().__init__()
        self.order = None
        self.order_notifications = []
        self.idle_observations = []

    def next(self):
        super().next()
        if len(self.batch_ids) == 1:
            # The first completed feed value exists before this ordinary order
            # is submitted. A low buy limit stays active across the pending wait.
            self.order = self.buy(
                data=self.datas[0],
                size=1,
                price=1.0,
                exectype=bt.Order.Limit,
            )
        elif len(self.batch_ids) == 2:
            self.cerebro.runstop()

    def notify_order(self, order):
        self.order_notifications.append(order.getstatusname())

    def notify_idle(self):
        batch = self.p.cohort.current_batch()
        self.idle_observations.append(
            {
                "slot_index": None if batch is None else batch.slot_index,
                "feed_lengths": tuple(len(data) for data in self.datas),
                "factor_advance_count": len(_FACTOR_ADVANCES),
                "order_status": None if self.order is None else self.order.getstatusname(),
                "order_alive": self.order is not None and self.order.alive(),
            }
        )


def test_pending_cohort_wait_polls_ordinary_broker_and_wakes_on_last_store_member():
    names = ("A", "B")
    calendar, sessions = _calendar(names, slots=2)
    first_slot, pending_slot = calendar.slots
    cohort = LiveBarCohort(
        "cohort-pending-wait",
        calendar,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=5_000_000_000,
    )
    clock = _InterruptibleClock(pending_slot.close_time)

    direct_bars = tuple(
        MappingProxyType(
            dict(
                _bar_event(
                    slot,
                    "A",
                    index + 1,
                    10.0 + index,
                    trading_day=sessions["member-A"].trading_day,
                    session_segment=sessions["member-A"].session_segment,
                )
            )
        )
        for index, slot in enumerate((first_slot, pending_slot))
    )
    store_first = dict(
        _bar_event(
            first_slot,
            "B",
            1,
            20.0,
            trading_day=sessions["member-B"].trading_day,
            session_segment=sessions["member-B"].session_segment,
        )
    )
    store_last = dict(
        _bar_event(
            pending_slot,
            "B",
            2,
            21.0,
            trading_day=sessions["member-B"].trading_day,
            session_segment=sessions["member-B"].session_segment,
        )
    )
    client = _DelayedEventClient(live={"B": (store_first,)})
    store = make_store(api=client, provider="okx", preserve_raw_bars=True)
    feeds = {
        "A": bt.feeds.BtApiFeed(
            dataname="A",
            live_bars=direct_bars,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        ),
        "B": bt.feeds.BtApiFeed(
            dataname="B",
            cohort_source_mode=True,
            store=store,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        ),
    }

    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    broker = bt.brokers.BackBroker()
    # BackBroker is the real bar-matching broker here. This opt-in only asks
    # Cerebro to call its normal next() maintenance while a cohort has no bar.
    broker.next_without_bar = True
    cerebro.setbroker(broker)
    for name in names:
        feed = feeds[name]
        cerebro.adddata(feed, name=name)
        cohort.register_member(
            f"member-{name}",
            feed,
            instrument=name,
            source_ref=f"feed-{name}",
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    plan = LiveFactorPlan(
        targets=names,
        groups=dict.fromkeys(names, "portfolio"),
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CohortClose,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=5_000_000_000,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(_PendingWaitStrategy, cohort=cohort, plan=plan)

    broker_steps = []
    original_broker_next = broker.next

    def observe_broker_maintenance():
        batch = cohort.current_batch()
        result = original_broker_next()
        active_orders = tuple(
            order
            for order in tuple(broker.pending) + tuple(broker.submitted)
            if order is not None and order.alive()
        )
        broker_steps.append(
            {
                "slot_index": None if batch is None else batch.slot_index,
                "feed_lengths": tuple(len(feeds[name]) for name in names),
                "order_statuses": tuple(order.getstatusname() for order in active_orders),
            }
        )
        return result

    broker.next = observe_broker_maintenance

    publish_errors = []

    def publish_last_member_after_wait_starts():
        try:
            if not clock.wait_started.wait(timeout=2.0):
                raise AssertionError("Cerebro never entered the pending cohort wait")
            if not client.notifier_bound.wait(timeout=2.0):
                raise AssertionError("Cerebro never registered the Store event notifier")
            client.publish_bar("B", store_last)
        except BaseException as exc:  # surfaced in the test thread after engine cleanup
            publish_errors.append(exc)

    _FACTOR_ADVANCES.clear()
    publisher = threading.Thread(target=publish_last_member_after_wait_starts, daemon=True)
    publisher.start()
    try:
        strategy = cerebro.run()[0]
    finally:
        publisher.join(timeout=2.0)

    assert not publisher.is_alive()
    assert publish_errors == []
    assert client.publish_count == 1
    assert clock.wait_results == [True]
    assert clock.wait_timeouts and clock.wait_timeouts[0] > 0
    assert client._event_notifier is None

    completed = cohort.current_batch()
    assert completed is not None and completed.status == "COMPLETE"
    assert completed.slot_index == 1
    assert len(strategy.batch_ids) == 2
    assert strategy.batch_ids[-1] == completed.batch_id
    assert strategy.batch_ids[0] != strategy.batch_ids[-1]
    assert len(_FACTOR_ADVANCES) == 2
    assert all(tuple(names) == advance for advance in _FACTOR_ADVANCES)
    assert tuple(len(feeds[name]) for name in names) == (2, 2)

    waiting_idles = [
        row
        for row in strategy.idle_observations
        if row["slot_index"] == 0 and row["feed_lengths"] == (1, 1)
    ]
    assert waiting_idles
    assert all(row["factor_advance_count"] == 1 for row in waiting_idles)
    assert any(row["order_status"] == "Accepted" and row["order_alive"] for row in waiting_idles)

    maintenance_steps = [
        row for row in broker_steps if row["slot_index"] == 0 and row["feed_lengths"] == (1, 1)
    ]
    assert any("Accepted" in row["order_statuses"] for row in maintenance_steps)
    assert strategy.order is not None and strategy.order.alive()
    assert strategy.order.getstatusname() == "Accepted"
    assert "Completed" not in strategy.order_notifications
