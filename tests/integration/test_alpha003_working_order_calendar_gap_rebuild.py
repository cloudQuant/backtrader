"""Keep an ordinary Broker order observable across a cohort calendar gap.

The old cohort freezes on one missing planned row while an order is still
working.  Cerebro's single terminal Broker poll receives a provider callback
through the ordinary Store queue.  A new whole-group epoch then replays the
old slots as history, preserves an explicit missing-row receipt, and permits
one new decision only on the first new live slot.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType, SimpleNamespace
import time

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import LiveFactorSet
from backtrader.research.live import LiveFactorOutputStatus, LiveFactorReadiness
from backtrader.research.live_cohort import LiveBarCohort
from tests.integration import test_live_alpha003_calendar_composition as calendar_fixtures
from tests.integration import test_live_alpha003_cohort_scenarios as trace_fixtures
from tests.integration import test_live_alpha003_parity as parity_fixtures
from tests.integration import test_live_factor_missing_gap_execution_rebuild as execution_fixtures


_TARGETS = (
    execution_fixtures.INSTRUMENT,
    "cu2510",
    "au2512",
)
_GAP_INDEX = 34
# Rebuild the entire source history from row zero. The missing slot resets the
# real 30-row Alpha003 warmup: rows 35..49 are historical prewarm and rows
# 50..64 are the remaining live rows before the first eligible decision.
_HISTORY_END = 50
_QUALIFIED_LIVE_INDEX = _GAP_INDEX + 30
# BtApiBroker.submit reaches the registered-sim insert synchronously from the
# Strategy callback, so the qualified decision itself is the final source row
# needed to observe the completed provider submit.
_TOTAL_ROWS = _QUALIFIED_LIVE_INDEX + 1
_RECOVERY_INDEX = _GAP_INDEX + 10
_FIELDS = parity_fixtures._OHLCV_FIELDS
_SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


class _Alpha003OrderStrategy(bt.Strategy):
    """Capture normal factor callbacks and optionally submit one live order."""

    params = (
        ("cohort", None),
        ("plan", None),
        ("coordinator", None),
        ("execution_facts", None),
        ("api", None),
        ("clock", None),
        ("provider_state", None),
        ("strategy_holder", None),
        ("submit_order", False),
    )

    def __init__(self):
        if self.p.strategy_holder is not None:
            self.p.strategy_holder["strategy"] = self
        self._data_by_target = {data._name: data for data in self.datas}
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            self._data_by_target,
            cohort=self.p.cohort,
        )
        self.observations = []
        self.orders_by_slot = []
        self.order = None
        self.order_batch = None
        self.terminal_notifications = []

    def prenext(self):
        self._capture()

    def nextstart(self):
        self._capture()

    def next(self):
        self._capture()

    def _capture(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.p.clock.advance_to(batch.available_at)
        snapshot = self.live_factors.snapshot()
        roles = {
            target: batch.receipt_for_feed(feed).envelope.source_role
            for target, feed in self._data_by_target.items()
        }
        self.observations.append(
            {
                "batch": batch,
                "snapshot": snapshot,
                "roles": roles,
                "feed_lengths": {
                    target: len(feed) for target, feed in self._data_by_target.items()
                },
            }
        )
        if (
            not self.p.submit_order
            or self.order is not None
            or snapshot.readiness is not LiveFactorReadiness.LIVE_READY
        ):
            return

        assert set(roles.values()) == {"live"}, roles
        outputs = tuple(snapshot.factors["alpha003"].values[target] for target in _TARGETS)
        assert all(output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE for output in outputs)
        assert all(math.isfinite(float(output.value)) for output in outputs)
        execution_fixtures._GapExecutionStrategy._submit_one_open(self, batch, snapshot)
        # The ordinary Broker reaches Store.submit_order synchronously. Only
        # its completed fake provider wrapper establishes a provider-side
        # working order.
        if self.p.provider_state.get("order_ref") is None:
            self.p.provider_state["working"] = False

    def notify_order(self, order):
        execution_fixtures._GapExecutionStrategy.notify_order(self, order)


@dataclass
class _EpochRun:
    strategy: _Alpha003OrderStrategy | None
    cohort: LiveBarCohort
    feeds: dict
    clock: object
    cerebro: bt.Cerebro
    store: object = None
    api: object = None
    broker: object = None
    journal: object = None
    coordinator: object = None
    execution_facts: object = None
    provider_state: dict | None = None
    query_observations: list | None = None
    strategy_holder: dict | None = None
    terminal_delivery: dict | None = None


def _fixture_inputs():
    # Reuse the accepted exchange-calendar fixture, including its planned
    # 3h31 lunch break, and shift only its UTC dates to the fake execution
    # facts' trading day.
    planner = calendar_fixtures._planner_grid()
    closes = [point.close_time + timedelta(days=2) for point in planner.minutes]
    while len(closes) < _TOTAL_ROWS:
        closes.append(closes[-1] + pd.Timedelta(minutes=1))
    grid = pd.DatetimeIndex(closes)
    assert grid[30] - grid[29] == pd.Timedelta(hours=3, minutes=31)
    assert grid[0].strftime("%Y%m%d") == "20261024"

    source_frames = parity_fixtures._minute_frames(max(320, len(grid)))
    source_names = tuple(source_frames)[: len(_TARGETS)]
    frames = {}
    for target, source_name in zip(_TARGETS, source_names):
        frame = source_frames[source_name].iloc[: len(grid)].copy(deep=True)
        frame.index = grid
        frames[target] = frame

    calendar, member_ids = parity_fixtures._calendar(_TARGETS, grid)
    calendar = replace(calendar, epoch_id=1, version="calendar-rules-1")
    return grid, frames, calendar, member_ids


def _bind_execution_fixture_trading_day(monkeypatch, calendar):
    """Bind the inherited CTP leaves to this replay's actual session day."""

    trading_days = {slot.trading_day for slot in calendar.slots}
    assert len(trading_days) == 1, trading_days
    trading_day = next(iter(trading_days))
    assert all(
        slot.close_time.astimezone(_SHANGHAI).strftime("%Y%m%d") == trading_day
        for slot in calendar.slots
    ), "the replay calendar must fit one Shanghai CTP TradingDay"

    facts_module = execution_fixtures.facts_fixtures
    monkeypatch.setattr(facts_module, "_TRADING_DAY", trading_day)
    quote = facts_module._quote

    def quote_for_replay_day(*, event_time, **kwargs):
        kwargs["trading_day"] = trading_day
        return quote(event_time=event_time, **kwargs)

    # The inherited helper's default argument was captured when its module
    # loaded, so pass the replay day explicitly for its initial source tick.
    monkeypatch.setattr(facts_module, "_quote", quote_for_replay_day)


class _CausalReplayClock(parity_fixtures._ReplayClock):
    """Advance receipt time only as complete source events become current."""

    # cerebro._cerebro.runnext caps a wait at this value while a Broker refresh
    # is due (``_LIVE_COHORT_BROKER_IDLE_POLL_SECONDS``). Stepping replay time
    # 50 ms at a time across a 60 s calendar slot costs ~1,200 loop iterations
    # per bar; jump straight to the next preloaded source event instead.
    _BROKER_IDLE_POLL_SECONDS = 0.05

    def __init__(self, now, *, source_events=()):
        super().__init__(now)
        self._source_events = tuple(sorted(source_events))
        self._source_cursor = 0

    def _next_source_event(self):
        while (
            self._source_cursor < len(self._source_events)
            and self._source_events[self._source_cursor] <= self.now
        ):
            self._source_cursor += 1
        if self._source_cursor < len(self._source_events):
            return self._source_events[self._source_cursor]
        return None

    def wait(self, timeout_seconds):
        timeout = max(0.0, float(timeout_seconds))
        if timeout and timeout <= self._BROKER_IDLE_POLL_SECONDS:
            event = self._next_source_event()
            if event is not None:
                timeout = max(timeout, (event - self.now).total_seconds())
        super().wait(timeout)

    def advance_to(self, source_time):
        if source_time > self.now:
            self.now = source_time

    def time_ns(self):
        now = self.utc_now().astimezone(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        elapsed = now - epoch
        return (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1_000


def _events(frames, *, omitted_target=None, explicit_missing_target=None):
    result = {}
    for target in _TARGETS:
        rows = list(parity_fixtures._bar_events(frames, target))
        if omitted_target == target:
            rows.pop(_GAP_INDEX)
        if explicit_missing_target == target:
            payload = dict(rows[_GAP_INDEX])
            payload.update(
                {
                    "close": math.nan,
                    "present": False,
                    "quality": "MISSING",
                    "quality_flags": ("MISSING_FIELDS",),
                    "missing_fields": ("close",),
                }
            )
            rows[_GAP_INDEX] = MappingProxyType(payload)
        result[target] = tuple(rows)
    return result


def _run_epoch(
    calendar,
    member_ids,
    events,
    *,
    cohort_id,
    history_bars=0,
    execution=False,
    submit_order=False,
    before_run=None,
    monkeypatch=None,
):
    cohort = LiveBarCohort(
        cohort_id,
        calendar,
        max_pending_slots=1,
        max_window_bars=len(calendar.slots),
        wait_timeout_ns=5_000_000_000,
    )
    clock = _CausalReplayClock(
        calendar.slots[0].close_time,
        source_events=(slot.close_time for slot in calendar.slots),
    )
    feeds = {}
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)

    for target in _TARGETS:
        source_rows = events[target]
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            historical_bars=source_rows[:history_bars],
            # Retain one exact history/live overlap; the duplicate belongs to
            # history and must not advance the cohort a second time.
            live_bars=source_rows[max(history_bars - 1, 0) :] if history_bars else source_rows,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[target] = feed
        cerebro.adddata(feed, name=target)
        cohort.register_member(
            member_ids[target],
            feed,
            instrument=target,
            source_ref="alpha003-calendar-gap:%s" % target,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )
    cohort.seal()

    store = api = broker = journal = coordinator = execution_facts = None
    provider_state = query_observations = None
    if execution:
        import backtrader.stores.execution_decision_journal as journal_module

        assert monkeypatch is not None
        monkeypatch.setattr(
            journal_module,
            "time",
            SimpleNamespace(time_ns=clock.time_ns, monotonic=time.monotonic),
        )
        facts_time = (
            calendar.slots[_QUALIFIED_LIVE_INDEX].close_time
            if history_bars
            else calendar.slots[29].close_time
        )
        (
            store,
            api,
            broker,
            journal,
            coordinator,
            execution_facts,
            provider_state,
            query_observations,
        ) = execution_fixtures._execution_stack(feeds, facts_time=facts_time)
        provider_submit = api.submit_order

        def observe_provider_submit(payload):
            result = provider_submit(payload)
            provider_state["order_ref"] = str(result["order_ref"])
            provider_state["working"] = True
            return result

        # Observe only the actual fake SDK submit after its native insert and
        # provider identity registration; Broker/Store admission, queueing,
        # dispatch and notifications remain production.
        api.submit_order = observe_provider_submit
        cerebro.setbroker(broker)

    plan = parity_fixtures._live_alpha003_plan(
        _TARGETS,
        calendar=calendar,
        mode="native",
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=cohort.max_window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=5.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    strategy_holder = {}
    cerebro.addstrategy(
        _Alpha003OrderStrategy,
        cohort=cohort,
        plan=plan,
        coordinator=coordinator,
        execution_facts=execution_facts,
        api=api,
        clock=clock,
        provider_state=provider_state,
        strategy_holder=strategy_holder,
        submit_order=submit_order,
    )
    epoch = _EpochRun(
        strategy=None,
        cohort=cohort,
        feeds=feeds,
        clock=clock,
        cerebro=cerebro,
        store=store,
        api=api,
        broker=broker,
        journal=journal,
        coordinator=coordinator,
        execution_facts=execution_facts,
        provider_state=provider_state,
        query_observations=query_observations,
        strategy_holder=strategy_holder,
    )
    if before_run is not None:
        before_run(epoch)
    strategy = cerebro.run(runonce=False, preload=False)[0]
    assert strategy_holder.get("strategy") is strategy
    epoch.strategy = strategy
    return epoch


def _run_epoch_timed(label, *args, **kwargs):
    started = time.perf_counter()
    print(f"[AC50-10] {label} started", flush=True)
    completed = False
    try:
        result = _run_epoch(*args, **kwargs)
        completed = True
        return result
    finally:
        elapsed = time.perf_counter() - started
        print(
            f"[AC50-10] {label} ended completed={completed} elapsed_s={elapsed:.3f}",
            flush=True,
        )


def _deliver_terminal_after_freeze(epoch):
    """Make the fake provider emit one terminal row on ordinary Store polling."""

    api = epoch.api
    original_poll = api.poll_broker_update
    delivery = {"attempted": False, "before": None}

    def poll_broker_update():
        if epoch.cohort.frozen and not delivery["attempted"]:
            strategy = epoch.strategy_holder["strategy"]
            assert strategy.order is not None and strategy.order.alive()
            assert epoch.provider_state["working"] is True
            order_ref = str(epoch.provider_state["order_ref"])
            next_slot_index = epoch.cohort._next_slot_index
            assert next_slot_index < len(epoch.cohort.calendar.slots)
            # The fake provider reports the terminal callback when the missing
            # planned slot becomes current. Advance the source clock before
            # the real journal callback path records its receive timestamp.
            callback_at = epoch.cohort.calendar.slots[next_slot_index].close_time
            epoch.clock.advance_to(callback_at)
            delivery["before"] = {
                "cohort_frozen": epoch.cohort.frozen,
                "provider_working": epoch.provider_state["working"],
                "local_order_alive": strategy.order.alive(),
                "order_ref": order_ref,
                "callback_at": callback_at,
            }
            api.emit_provider_order_callback(
                order_ref,
                status="canceled",
                filled=0,
                remaining=1,
            )
            epoch.provider_state["order_ref"] = order_ref
            epoch.provider_state["working"] = False
            delivery["attempted"] = True
        return original_poll()

    api.poll_broker_update = poll_broker_update
    epoch.terminal_delivery = delivery


def _same_float(left, right, context):
    left, right = float(left), float(right)
    if math.isnan(left):
        assert math.isnan(right), context
    else:
        assert left == right, (context, left, right)


def _assert_rebuilt_suffix_matches(reference, rebuilt, *, first_row, rows):
    assert len(reference.strategy.observations) == len(rebuilt.strategy.observations) == rows
    for index in range(first_row, rows):
        left = reference.strategy.observations[index]["snapshot"]
        right = rebuilt.strategy.observations[index]["snapshot"]
        assert left.close_time == right.close_time
        for target in _TARGETS:
            left_output = left.factors["alpha003"].values[target]
            right_output = right.factors["alpha003"].values[target]
            assert (
                left_output.status,
                left_output.reason,
                left_output.present,
                left_output.quality,
            ) == (
                right_output.status,
                right_output.reason,
                right_output.present,
                right_output.quality,
            ), (
                index,
                target,
            )
            _same_float(left_output.value, right_output.value, (index, target))

    left_factor = reference.strategy.live_factors.factor_instances["alpha003"]["default"]
    right_factor = rebuilt.strategy.live_factors.factor_instances["alpha003"]["default"]
    left_values, left_reasons = trace_fixtures._node_values_and_reasons(left_factor, _TARGETS, rows)
    right_values, right_reasons = trace_fixtures._node_values_and_reasons(
        right_factor, _TARGETS, rows
    )
    assert set(left_values) == set(right_values)
    for node_name in left_values:
        if node_name.startswith("rank_"):
            for target_index, target in enumerate(_TARGETS):
                for index in range(first_row, rows):
                    _same_float(
                        left_values[node_name][target_index][index],
                        right_values[node_name][target_index][index],
                        (node_name, target, index),
                    )
                assert (
                    left_reasons[node_name][target_index][first_row:]
                    == right_reasons[node_name][target_index][first_row:]
                ), (node_name, target)
        else:
            for index in range(first_row, rows):
                _same_float(
                    left_values[node_name][index],
                    right_values[node_name][index],
                    (node_name, index),
                )
            assert left_reasons[node_name][first_row:] == right_reasons[node_name][first_row:]


@pytest.mark.integration
def test_working_order_is_polled_at_gap_freeze_then_new_epoch_replays_history_without_old_decision(
    monkeypatch,
):
    inputs = _fixture_inputs()
    _test_working_order_calendar_gap_rebuild(*inputs, monkeypatch=monkeypatch)


def _test_working_order_calendar_gap_rebuild(
    grid, frames, epoch_one_calendar, member_ids, *, monkeypatch
):
    _bind_execution_fixture_trading_day(monkeypatch, epoch_one_calendar)

    # A real Store/Broker path admits an order once the full Alpha003 history
    # window is available. One member then omits planned slot 34 while the
    # provider still reports that order working.
    old_calendar = epoch_one_calendar
    old_events = _events(frames, omitted_target=_TARGETS[-1])
    old = _run_epoch_timed(
        "old_epoch",
        old_calendar,
        member_ids,
        old_events,
        cohort_id="alpha003-working-order-old-epoch",
        execution=True,
        submit_order=True,
        before_run=_deliver_terminal_after_freeze,
        monkeypatch=monkeypatch,
    )
    strategy = old.strategy
    assert strategy is not None
    delivery = old.terminal_delivery
    assert delivery is not None
    assert delivery["attempted"] is True and delivery["before"] is not None

    assert old.cohort.epoch_id == 1 and old.cohort.frozen is True
    assert old.cohort.frozen_reason == "planned_gap_requires_rebuild"
    assert old.cohort._next_slot_index == _GAP_INDEX
    assert len(old.cohort.gaps) == 1
    gap = old.cohort.gaps[0]
    assert gap.slot_index == _GAP_INDEX
    assert gap.slot_id == old_calendar.slots[_GAP_INDEX].slot_id
    assert gap.close_time == old_calendar.slots[_GAP_INDEX].close_time
    assert gap.missing_member_ids == (member_ids[_TARGETS[-1]],)
    assert [row["batch"].slot_index for row in strategy.observations] == list(range(_GAP_INDEX))
    assert [row["feed_lengths"] for row in strategy.observations] == [
        dict.fromkeys(_TARGETS, index + 1) for index in range(_GAP_INDEX)
    ]
    assert [len(feed) for feed in old.feeds.values()] == [_GAP_INDEX] * len(_TARGETS)
    assert strategy.orders_by_slot == [29]
    assert strategy.order_batch is strategy.observations[29]["batch"]
    assert strategy.order_batch.slot_index == 29
    assert old.execution_facts.open_risk_ready is True
    assert delivery["before"] == {
        "cohort_frozen": True,
        "provider_working": True,
        "local_order_alive": True,
        "order_ref": str(old.api.native_calls[-1][3]),
        "callback_at": old_calendar.slots[_GAP_INDEX].close_time,
    }
    assert any(
        observation["working"] is True and observation["cohort_frozen"] is False
        for observation in old.query_observations
    ), old.query_observations

    # The provider callback is drained on the ordinary final Broker poll.
    # No ongoing post-freeze polling is inferred after Cerebro stops the epoch.
    assert old.provider_state["working"] is False
    assert strategy.order.status == bt.Order.Canceled
    assert strategy.order.alive() is False
    assert len(strategy.terminal_notifications) == 1
    terminal = strategy.terminal_notifications[0]
    assert terminal["order_ref"] == strategy.order.ref
    assert terminal["intent_id"] == strategy.order.info["factor_intent_id"]
    assert terminal["cohort_frozen"] is True
    assert terminal["next_slot_index"] == _GAP_INDEX
    assert terminal["batch_slot_index"] == _GAP_INDEX - 1
    assert [call[0] for call in old.api.native_calls] == ["insert"]
    assert old.journal.decision_capacity_snapshot().base_record_count == 1

    # Rebuild the whole group on the same ordered slots under a new epoch.
    # The old missing slot is retained as an explicit MISSING history receipt;
    # the final history row overlaps live input and is consumed only once.
    new_calendar = replace(epoch_one_calendar, epoch_id=2, version="calendar-rules-2")
    rebuilt_events = _events(frames, explicit_missing_target=_TARGETS[-1])
    rebuilt = _run_epoch_timed(
        "rebuilt_epoch",
        new_calendar,
        member_ids,
        rebuilt_events,
        cohort_id="alpha003-working-order-rebuilt-epoch",
        history_bars=_HISTORY_END,
        execution=True,
        submit_order=True,
        monkeypatch=monkeypatch,
    )
    reference = _run_epoch_timed(
        "full_live_reference",
        new_calendar,
        member_ids,
        rebuilt_events,
        cohort_id="alpha003-working-order-live-reference",
        submit_order=False,
    )

    rebuilt_strategy = rebuilt.strategy
    reference_strategy = reference.strategy
    assert rebuilt_strategy is not None and reference_strategy is not None
    assert old.cohort.frozen is True and old.cohort._next_slot_index == _GAP_INDEX
    assert [len(feed) for feed in old.feeds.values()] == [_GAP_INDEX] * len(_TARGETS)
    assert rebuilt.cohort.epoch_id == 2 and rebuilt.cohort.frozen is False
    assert rebuilt.cohort.cohort_id != old.cohort.cohort_id
    assert [row["batch"].slot_index for row in rebuilt_strategy.observations] == list(
        range(len(new_calendar.slots))
    )
    assert len(rebuilt_strategy.observations) == len(grid) == _TOTAL_ROWS
    assert all(
        set(row["roles"].values()) == {"history"}
        for row in rebuilt_strategy.observations[:_HISTORY_END]
    )
    assert set(rebuilt_strategy.observations[_HISTORY_END]["roles"].values()) == {"live"}
    assert all(
        row["snapshot"].readiness is not LiveFactorReadiness.LIVE_READY
        for row in rebuilt_strategy.observations[:_HISTORY_END]
    )

    # Historical slots cannot be reconsidered as live decisions. The only
    # order in the rebuilt run belongs to the new live grid after the overlap.
    assert all(
        row["snapshot"].readiness is not LiveFactorReadiness.LIVE_READY
        for row in rebuilt_strategy.observations[_HISTORY_END:_QUALIFIED_LIVE_INDEX]
    )
    assert rebuilt_strategy.orders_by_slot == [_QUALIFIED_LIVE_INDEX]
    assert (
        rebuilt_strategy.order_batch
        is rebuilt_strategy.observations[_QUALIFIED_LIVE_INDEX]["batch"]
    )
    assert (
        rebuilt_strategy.order_batch.close_time
        == new_calendar.slots[_QUALIFIED_LIVE_INDEX].close_time
    )
    assert rebuilt.coordinator.run_order_count() == 1
    assert rebuilt.journal.decision_capacity_snapshot().base_record_count == 1
    assert rebuilt_strategy.order is not None
    assert [call[0] for call in rebuilt.api.native_calls] == ["insert"], {
        "order_status": rebuilt_strategy.order.getstatusname(),
        "order_info": {
            key: rebuilt_strategy.order.info.get(key)
            for key in (
                "factor_intent_id",
                "factor_dispatch_state",
                "factor_dispatch_outcome",
                "execution_unknown",
                "error_code",
            )
        },
        "provider_state": dict(rebuilt.provider_state),
    }
    assert rebuilt.provider_state["working"] is True
    assert rebuilt.provider_state["order_ref"] == str(rebuilt.api.native_calls[0][3])
    assert rebuilt_strategy.order.alive() is True
    intent = rebuilt.journal.intent(rebuilt_strategy.order.info["factor_intent_id"])
    assert intent is not None
    decision = rebuilt.journal.decision(intent.decision_id)
    assert decision is not None
    assert decision.key.cohort_id == rebuilt.cohort.cohort_id
    assert decision.key.close_time == new_calendar.slots[
        _QUALIFIED_LIVE_INDEX
    ].close_time.isoformat().replace("+00:00", "Z")

    # Recovery after the missing row matches the same production graph run on
    # a full-live stream, per asset and per intermediate node/reason.
    gap_batch = rebuilt_strategy.observations[_GAP_INDEX]["batch"]
    missing = gap_batch.receipt_for_feed(rebuilt.feeds[_TARGETS[-1]])
    assert missing.complete is True and missing.present is False
    assert missing.quality == "MISSING"
    gap_output = (
        rebuilt_strategy.observations[_GAP_INDEX]["snapshot"]
        .factors["alpha003"]
        .values[_TARGETS[-1]]
    )
    assert gap_output.status is LiveFactorOutputStatus.OUTPUT_UNAVAILABLE
    assert gap_output.present is False and gap_output.quality == "MISSING"
    before_recovery = (
        rebuilt_strategy.observations[_RECOVERY_INDEX - 1]["snapshot"]
        .factors["alpha003"]
        .values[_TARGETS[-1]]
    )
    assert before_recovery.status is LiveFactorOutputStatus.OUTPUT_UNAVAILABLE
    assert before_recovery.reason == "INCOMPLETE_WINDOW"
    recovered = (
        rebuilt_strategy.observations[_RECOVERY_INDEX]["snapshot"]
        .factors["alpha003"]
        .values[_TARGETS[-1]]
    )
    assert recovered.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE
    assert recovered.present is True and math.isfinite(float(recovered.value))
    _assert_rebuilt_suffix_matches(
        reference,
        rebuilt,
        first_row=_RECOVERY_INDEX,
        rows=len(grid),
    )
