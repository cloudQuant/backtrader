"""Cooperative live-cohort prepare budget and pending-wait quote regressions."""

from __future__ import annotations

from datetime import timedelta
import backtrader as bt

from backtrader.research import FactorSpec, LiveFactorPlan
from backtrader.research.live_cohort import LiveBarCohort
from tests.fixtures.fake_btapi import FakeBtApiClient, make_orderbook, make_store
from tests.integration.test_iteration50_handoff_contract_gaps import (
    _FACTOR_CALLS,
    START,
    CaptureStrategy,
    CloseValue,
    ReplayClock,
    _single_member_calendar,
    _tick,
)
from tests.integration.test_live_factor_cohort_composition import (
    CohortClose,
    CohortStrategy,
    _bar_event,
    _calendar,
)


class _StopAfterTwoBatches(CohortStrategy):
    params = (
        ("cohort", None),
        ("plan", None),
        ("raise_on_notify", False),
        ("timeline", None),
        ("client", None),
        ("delayed_release", None),
    )

    def __init__(self):
        super().__init__()
        self.idle_calls = 0
        self.probe_order = None
        self.first_batch_source_state = None
        self.batch_closes = []

    def notify_idle(self):
        self.idle_calls += 1
        self.p.timeline.append(("idle", len(self.batch_ids)))

    def next(self):
        super().next()
        self.p.timeline.append(("strategy_batch", len(self.batch_ids)))
        self.batch_closes.append(tuple(float(data.close[0]) for data in self.datas))
        if len(self.batch_ids) == 1:
            self.first_batch_source_state = {
                "orderbooks": {
                    symbol: tuple(event.timestamp for event in queue)
                    for symbol, queue in self.p.client.live_orderbooks.items()
                },
                "bar_poll_counts": dict(self.p.client.bar_poll_counts),
            }
            # Submit through ordinary Strategy/BackBroker after a real shared
            # batch, then keep the unfilled Limit live during pending waits.
            self.probe_order = self.buy(size=1, exectype=bt.Order.Limit, price=1.0)
            self.p.delayed_release["first_batch_delivered"] = True
        if len(self.batch_ids) == 2:
            self.cerebro.runstop()


class _DelayedBarClient(FakeBtApiClient):
    def __init__(self, *, timeline, delayed_bar, live):
        super().__init__(
            live=live,
            live_ticks={"A": (), "B": (), "C": ()},
            live_orderbooks={"A": (), "B": (), "C": ()},
        )
        self.timeline = timeline
        self.delayed_bar = delayed_bar
        self.delayed_released = False
        self.notifier = None
        self.bar_poll_counts = {"A": 0, "B": 0, "C": 0}
        self.book_sequence_by_timestamp = {"A": {}, "B": {}, "C": {}}

    def set_live_bar_event_notifier(self, callback):
        self.notifier = callback

    def release_delayed_bar(self):
        if self.delayed_released:
            return
        self.live["C"].append(dict(self.delayed_bar))
        self.delayed_released = True
        self.timeline.append(("delayed_bar_released", "C", 2))
        assert callable(self.notifier)
        self.notifier()


class _BudgetClock:
    def __init__(
        self,
        now,
        timeline,
        *,
        delayed_client=None,
        delayed_release=None,
        release_orderbooks=None,
    ):
        self.now = now
        self.monotonic = 1_000
        self.turn_start = self.monotonic
        self.turn_id = 0
        self.timeline = timeline
        self.waits = []
        self.delayed_client = delayed_client
        self.delayed_release = delayed_release
        self.release_orderbooks = release_orderbooks
        self.orderbooks_released = False

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def _advance_wait(self, timeout_seconds):
        timeout = float(timeout_seconds)
        self.waits.append(timeout)
        self.timeline.append(("wait", timeout))
        self.monotonic += max(1, int(timeout * 1_000_000_000))
        self.now += timedelta(seconds=timeout)
        if self.release_orderbooks is not None and not self.orderbooks_released:
            self.release_orderbooks()
            self.orderbooks_released = True
        released = False
        if (
            self.delayed_client is not None
            and self.delayed_release["first_batch_delivered"]
            and not self.delayed_client.delayed_released
        ):
            self.delayed_client.release_delayed_bar()
            released = True
        self.turn_start = self.monotonic
        self.turn_id = len(self.waits)
        return released

    def wait(self, timeout_seconds):
        self._advance_wait(timeout_seconds)

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        released = self._advance_wait(timeout_seconds)
        woke = bool(wait_for_event(0.0)) if released else False
        self.timeline.append(("wait_woke", woke))
        return woke


def test_prepare_budget_prioritizes_ready_batch_and_rotates_across_busy_feeds():
    names = ("A", "B", "C")
    calendar, sessions = _calendar(names, slots=2)
    timeline = []
    delayed_release = {"first_batch_delivered": False}
    slot0, slot1 = calendar.slots

    def bar(symbol, slot, sequence, close):
        return _bar_event(
            slot,
            symbol,
            sequence,
            close,
            trading_day=sessions[f"member-{symbol}"].trading_day,
            session_segment=sessions[f"member-{symbol}"].session_segment,
        )

    delayed_bar = bar("C", slot1, 2, 32.0)
    client = _DelayedBarClient(
        timeline=timeline,
        delayed_bar=delayed_bar,
        live={"A": (), "B": (), "C": ()},
    )
    for symbol in names:
        if symbol != "C":
            client.live[symbol].append(dict(bar(symbol, slot1, 2, 30.0 + names.index(symbol))))
        books = []
        for sequence in range(1, 13):
            orderbook = make_orderbook(
                sequence,
                100.0 + sequence,
                101.0 + sequence,
                symbol=symbol,
            )
            event_time = slot1.close_time - timedelta(milliseconds=13 - sequence)
            orderbook.timestamp = event_time.timestamp()
            orderbook.local_time = event_time.timestamp()
            orderbook.datetime = event_time.replace(tzinfo=None)
            client.book_sequence_by_timestamp[symbol][orderbook.timestamp] = sequence
            books.append(orderbook)
        if symbol == "A":
            delayed_orderbooks = books
        else:
            client.live_orderbooks[symbol].extend(books)

    def release_orderbooks():
        client.live_orderbooks["A"].extend(delayed_orderbooks)
        timeline.append(("delayed_orderbooks_released", "A", len(delayed_orderbooks)))

    clock = _BudgetClock(
        calendar.slots[-1].close_time + timedelta(seconds=5),
        timeline,
        delayed_client=client,
        delayed_release=delayed_release,
        release_orderbooks=release_orderbooks,
    )
    original_poll_bar = client.poll_bar
    original_poll_orderbook = client.poll_orderbook
    polled_bars = {symbol: [] for symbol in names}
    polled_orderbooks = {symbol: [] for symbol in names}
    poll_costs_ns = []

    def record_nonempty_poll(kind, symbol, sequence):
        before = clock.monotonic
        clock.monotonic += 6_000_000
        cost = clock.monotonic - before
        poll_costs_ns.append(cost)
        timeline.append(
            (
                "nonempty_poll",
                kind,
                symbol,
                sequence,
                cost,
                clock.monotonic - clock.turn_start,
                clock.turn_id,
            )
        )

    def poll_bar(symbol):
        event = original_poll_bar(symbol)
        if event is None:
            return None
        sequence = event["bar_sequence"]
        client.bar_poll_counts[symbol] += 1
        polled_bars[symbol].append(sequence)
        record_nonempty_poll("bar", symbol, sequence)
        timeline.append(("bar_sequence", symbol, sequence))
        return event

    def poll_orderbook(symbol):
        timeline.append(("orderbook_poll", clock.turn_id, symbol))
        event = original_poll_orderbook(symbol)
        if event is None:
            return None
        sequence = client.book_sequence_by_timestamp[symbol][event.timestamp]
        polled_orderbooks[symbol].append(sequence)
        record_nonempty_poll("orderbook", symbol, sequence)
        return event

    client.poll_bar = poll_bar
    client.poll_orderbook = poll_orderbook
    store = make_store(api=client, provider="okx", preserve_raw_bars=True)
    feeds = {
        symbol: bt.feeds.BtApiFeed(
            dataname=symbol,
            store=store,
            live_bars=(bar(symbol, slot0, 1, 20.0 + names.index(symbol)),),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        for symbol in names
    }
    cohort = LiveBarCohort(
        "cohort-prepare-budget",
        calendar,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=5_000_000_000,
    )
    for symbol in names:
        cohort.register_member(
            f"member-{symbol}",
            feeds[symbol],
            instrument=symbol,
            source_ref=f"feed-{symbol}",
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
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    broker = bt.brokers.BackBroker()
    # This explicitly opts the local ordinary broker into no-bar maintenance
    # for the pending source wait; the normal BackBroker.next implementation
    # still processes the accepted Limit order.
    broker.next_without_bar = True
    original_broker_next = broker.next

    def tracked_broker_next():
        timeline.append(("broker_next",))
        return original_broker_next()

    broker.next = tracked_broker_next
    cerebro.setbroker(broker)
    for symbol in names:
        cerebro.adddata(feeds[symbol], name=symbol)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _StopAfterTwoBatches,
        cohort=cohort,
        plan=plan,
        timeline=timeline,
        client=client,
        delayed_release=delayed_release,
    )

    [strategy] = cerebro.run()

    first_batch = timeline.index(("strategy_batch", 1))
    first_overrun_before_batch = next(
        index
        for index, row in enumerate(timeline[:first_batch])
        if row[0] == "nonempty_poll" and row[1] == "orderbook" and row[5] > 10_000_000
    )
    overrun_turn = timeline[first_overrun_before_batch][6]
    same_turn_orderbooks = [
        row
        for row in timeline[:first_batch]
        if row[0] == "nonempty_poll" and row[1] == "orderbook" and row[6] == overrun_turn
    ]
    same_turn_attempts = [
        row
        for row in timeline[:first_batch]
        if row[0] == "orderbook_poll" and row[1] == overrun_turn
    ]
    assert tuple(row[2] for row in same_turn_attempts[:2]) == ("A", "B"), (
        overrun_turn,
        same_turn_attempts,
        same_turn_orderbooks,
        [row for row in timeline if row[0] in ("wait", "nonempty_poll")],
    )
    same_turn_events = [
        row
        for row in timeline[:first_batch]
        if row[0] == "nonempty_poll" and row[6] == overrun_turn
    ]
    assert tuple((row[1], row[2], row[5]) for row in same_turn_events) == (
        ("bar", "A", 6_000_000),
        ("orderbook", "B", 12_000_000),
    ), same_turn_events
    assert tuple(row[2] for row in same_turn_orderbooks) == ("B",)
    assert same_turn_orderbooks[-1][5] == 12_000_000
    next_turn_first_orderbook_attempt = next(
        row for row in timeline if row[0] == "orderbook_poll" and row[1] == overrun_turn + 1
    )
    assert next_turn_first_orderbook_attempt[2] == "C"
    remaining_at_first_batch = strategy.first_batch_source_state["orderbooks"]
    assert all(remaining_at_first_batch[symbol] for symbol in names)
    assert strategy.first_batch_source_state["bar_poll_counts"] == {
        "A": 1,
        "B": 0,
        "C": 0,
    }
    assert delayed_release["first_batch_delivered"] is True
    release = timeline.index(("delayed_bar_released", "C", 2))
    wait_before_release = max(
        index for index, row in enumerate(timeline[:release]) if row[0] == "wait"
    )
    assert ("wait_woke", True) in timeline
    broker_after_first_batch = next(
        index
        for index, row in enumerate(timeline[first_batch + 1 : release], first_batch + 1)
        if row[0] == "broker_next"
    )
    idle_after_first_batch = next(
        index
        for index, row in enumerate(timeline[first_batch + 1 : release], first_batch + 1)
        if row == ("idle", 1)
    )
    last_member_bar = timeline.index(("bar_sequence", "C", 2))
    assert first_batch < broker_after_first_batch < idle_after_first_batch
    assert idle_after_first_batch < wait_before_release
    assert wait_before_release < release < last_member_bar
    assert len(strategy.batch_ids) == 2
    assert tuple(len(feeds[symbol]) for symbol in names) == (2, 2, 2)
    assert tuple(strategy.batch_closes) == ((20.0, 21.0, 22.0), (30.0, 31.0, 32.0))
    assert all(polled_bars[symbol] == [2] for symbol in names)
    for symbol in names:
        assert polled_orderbooks[symbol] == sorted(set(polled_orderbooks[symbol]))
        assert len(polled_orderbooks[symbol]) + len(client.live_orderbooks[symbol]) == 12
    assert poll_costs_ns and set(poll_costs_ns) == {6_000_000}
    post_first_batch_overrun_indices = [
        index
        for index, row in enumerate(timeline[first_batch:], first_batch)
        if row[0] == "nonempty_poll" and row[1] == "orderbook" and row[-2] > 10_000_000
    ]
    assert len(post_first_batch_overrun_indices) >= 9
    assert (
        tuple(timeline[index][2] for index in post_first_batch_overrun_indices[:9])
        == (
            "A",
            "B",
            "C",
        )
        * 3
    )
    nonempty_poll_indices = [
        index for index, row in enumerate(timeline) if row[0] == "nonempty_poll"
    ]
    for overrun_index in post_first_batch_overrun_indices[:9]:
        next_poll = next(index for index in nonempty_poll_indices if index > overrun_index)
        broker_index = next(
            index
            for index, row in enumerate(timeline[overrun_index + 1 : next_poll], overrun_index + 1)
            if row[0] == "broker_next"
        )
        idle_index = next(
            index
            for index, row in enumerate(timeline[overrun_index + 1 : next_poll], overrun_index + 1)
            if row == ("idle", 1)
        )
        wait_index = next(
            index
            for index, row in enumerate(timeline[overrun_index + 1 : next_poll], overrun_index + 1)
            if row[0] == "wait"
        )
        assert overrun_index < broker_index < idle_index < wait_index < next_poll
    assert len(clock.waits) >= 3 and max(clock.waits) <= 0.05
    assert strategy.idle_calls >= 3
    assert strategy.probe_order is not None
    assert strategy.probe_order.status != strategy.probe_order.Completed


class _PendingQuoteClient(FakeBtApiClient):
    def __init__(self, *, timeline):
        first = _tick(START + timedelta(seconds=30), sequence=1, price=100.0)
        next_bucket = _tick(START + timedelta(minutes=1, seconds=1), sequence=2, price=101.0)
        super().__init__(live_ticks={"A": (first, next_bucket)})
        self.timeline = timeline
        self.notifier = None
        self.published = False
        self.completed = False

    def set_live_bar_event_notifier(self, callback):
        self.notifier = callback

    def publish_intermediate_quote(self):
        assert callable(self.notifier)
        self.live_ticks["A"].append(
            _tick(START + timedelta(minutes=1, seconds=30), sequence=3, price=102.0)
        )
        self.published = True
        self.timeline.append(("published", 3))
        self.notifier()

    def publish_closing_quote(self):
        assert callable(self.notifier)
        self.live_ticks["A"].append(
            _tick(START + timedelta(minutes=2, seconds=1), sequence=4, price=103.0)
        )
        self.completed = True
        self.timeline.append(("published", 4))
        self.notifier()


class _PendingQuoteClock(ReplayClock):
    def __init__(self, now, *, client, timeline, target_time):
        super().__init__(now)
        self.client = client
        self.timeline = timeline
        self.target_time = target_time
        self.interruptible_waits = []

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        self.interruptible_waits.append(float(timeout_seconds))
        self.timeline.append(("wait", len(self.interruptible_waits)))
        if not self.client.published:
            self.client.publish_intermediate_quote()
            self.now = START + timedelta(minutes=1, seconds=30, milliseconds=50)
            return bool(wait_for_event(0.0))
        if not self.client.completed:
            self.client.publish_closing_quote()
            self.now = self.target_time
            return bool(wait_for_event(0.0))
        raise AssertionError("pending quote fixture waited after the closing quote")


class _StopAfterPendingQuote(CaptureStrategy):
    def __init__(self):
        super().__init__()
        self.pending_observations = []

    def notify_idle(self):
        latest = self.tick_events[-1] if self.tick_events else None
        first_event = self.rows[0]["receipt"].envelope.event_ref if self.rows else None
        self.pending_observations.append(
            {
                "feed_length": len(self.data),
                "latest_sequence": getattr(latest, "ingest_seq", None),
                "sealed_close": getattr(first_event, "close", None),
                "sealed_cutoff": getattr(first_event, "quote_cutoff_seq", None),
            }
        )

    def next(self):
        super().next()
        if len(self.rows) == 2:
            self.cerebro.runstop()


def test_pending_wait_accepts_fresh_execution_quote_without_mutating_sealed_bar():
    _FACTOR_CALLS.clear()
    timeline = []
    calendar = _single_member_calendar(2)
    client = _PendingQuoteClient(timeline=timeline)
    clock = _PendingQuoteClock(
        calendar.slots[0].close_time + timedelta(seconds=1),
        client=client,
        timeline=timeline,
        target_time=calendar.slots[-1].close_time + timedelta(seconds=2),
    )
    store = make_store(api=client, provider="okx", preserve_raw_bars=True)
    feed = bt.feeds.BtApiFeed(
        dataname="A",
        store=store,
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        dispatch_ticks=True,
        closed_bar_quote_capture=True,
        clock=clock,
    )
    cohort = LiveBarCohort(
        "cohort-pending-quote",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    cohort.register_member(
        "member-A",
        feed,
        instrument="A",
        source_ref="feed-A",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    plan = LiveFactorPlan(
        targets=("A",),
        groups={"A": "portfolio"},
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CloseValue,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.adddata(feed, name="A")
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(_StopAfterPendingQuote, cohort=cohort, plan=plan)

    [strategy] = cerebro.run()

    assert client.published is True
    assert any(row[0] == "wait" for row in timeline)
    assert len(strategy.rows) == 2
    assert any(
        row["feed_length"] == 1
        and row["latest_sequence"] == 3
        and row["sealed_close"] == 100.0
        and row["sealed_cutoff"] == 1
        for row in strategy.pending_observations
    )
    first = strategy.rows[0]
    sealed_event = first["receipt"].envelope.event_ref
    assert first["batch"].slot_index == 0
    assert sealed_event.close == 100.0
    assert sealed_event.quote_cutoff_seq == 1
    assert tuple(item["ingest_seq"] for item in sealed_event.quote_events) == (1,)
    latest = strategy.tick_events[-1]
    assert latest.ingest_seq == 4 and latest.price == 103.0
    assert sealed_event.close == 100.0
    assert sealed_event.quote_cutoff_seq == 1
    assert tuple(item["ingest_seq"] for item in sealed_event.quote_events) == (1,)
    assert tuple(len(data) for data in strategy.datas) == (2,)
    assert _FACTOR_CALLS == [100.0, 102.0]
