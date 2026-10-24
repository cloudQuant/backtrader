"""Strict ordinary-Strategy contracts for cohort-bound factor graphs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from types import MappingProxyType

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError, ResearchConfigError
from backtrader.metabase import OwnerContext
from backtrader.research import (
    FactorIndicator,
    FactorSpec,
    FactorStrategy,
    LiveFactorPlan,
    LiveFactorOutputStatus,
    LiveFactorReadiness,
    LiveFactorSet,
    ResearchSpec,
    align_to_grid,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)
from backtrader.research.operators import CrossSectionalRank
from backtrader.research.strict import live_source_binding_active, live_source_binding_scope
from backtrader.research.alpha101 import get_alpha


UTC = timezone.utc
START = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


class ReplayClock:
    """Deterministic source clock that advances only to scheduled availability."""

    def __init__(self, available_times, *, now=START):
        self.now = now
        self.monotonic = 1_000
        self.available_times = tuple(sorted(available_times))
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        future = [value for value in self.available_times if value > self.now]
        if future:
            target = future[0]
            elapsed = min((target - self.now).total_seconds(), timeout_seconds)
        else:
            elapsed = timeout_seconds
        self.now += timedelta(seconds=elapsed)
        self.monotonic += max(1, int(elapsed * 1_000_000_000))


class WallClock:
    """Production-shaped clock whose UTC value comes from datetime.now()."""

    def utc_now(self):
        return datetime.now(UTC)

    def monotonic_ns(self):
        return time.monotonic_ns()

    def wait(self, timeout_seconds):
        time.sleep(timeout_seconds)


class ScaledClose(FactorIndicator):
    lines = ("factor",)
    params = (("scale", 1.0),)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("close")

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0] * self.p.scale

    @classmethod
    def build(cls, ctx, scale=1.0):
        return ctx.close * scale


def _raise_live_factor_runtime_error(*_values):
    raise LookupError("synthetic live factor runtime failure")


class FailingLiveFactor(ScaledClose):
    """Factor whose native and expression callbacks fail during real execution."""

    def next(self):
        raise LookupError("synthetic live factor runtime failure")

    @classmethod
    def build(cls, ctx, scale=1.0):
        return ctx.apply(_raise_live_factor_runtime_error, ctx.close)


class OrdinaryStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.snapshots = []

    def next(self):
        # Cerebro publishes a full batch before invoking an ordinary Strategy.
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.snapshots.append(self.live_factors.snapshot())


class UnexplainedNaN(ScaledClose):
    """A custom native formula that supplies no operator reason for NaN."""

    def next(self):
        for data in self.datas:
            self.outputs[data].factor[0] = float("nan")


def _bar(slot, sequence, close, source_role, *, available_at=None):
    return MappingProxyType(
        {
            "instrument": "SYM",
            "symbol": "SYM",
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time if available_at is None else available_at,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "clock-A",
            "connection_generation": "generation-1",
            "bar_sequence": sequence,
            "bar_id": "bar-%d" % sequence,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": float(sequence),
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "synthetic-%s" % source_role,
        }
    )


def _make_inputs(
    *,
    count=70,
    mode="native",
    activated=True,
    bad_close=None,
    base=100.0,
    start=START,
    include_live=True,
    availability_delay_seconds=0.0,
    max_live_bar_age_seconds=60.0,
    max_future_skew_seconds=0.0,
    clock=None,
    indicator=ScaledClose,
):
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-%d" % index,
            bucket_start=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            trading_day=start.date().isoformat(),
            session_segment="regular",
        )
        for index in range(count)
    )
    calendar = LiveCohortCalendar(
        calendar_id="calendar-A",
        version="v1",
        epoch_id=7,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-A",
        session_semantics="session-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "cohort-A",
        calendar,
        max_pending_slots=2,
        max_window_bars=count,
        wait_timeout_ns=60_000_000_000,
    )
    values = [base + index for index in range(count)]
    if bad_close is not None:
        values[-1] = bad_close
    history_slots = slots[:-1] if include_live else slots
    historical = tuple(
        _bar(slot, index + 1, values[index], "history") for index, slot in enumerate(history_slots)
    )
    live = (
        (
            _bar(
                slots[-1],
                count,
                values[-1],
                "live",
                available_at=slots[-1].close_time + timedelta(seconds=availability_delay_seconds),
            ),
        )
        if include_live
        else ()
    )
    feed = bt.feeds.BtApiFeed(
        dataname="SYM",
        historical_bars=historical,
        live_bars=live,
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=3,
        preload=False,
        runonce=False,
    )
    cerebro.adddata(feed, name="A")
    cohort.register_member(
        "member-A",
        feed,
        instrument="SYM",
        source_ref="feed-A",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    factor_name = (
        "alpha%03d" % indicator.alpha_id if hasattr(indicator, "alpha_id") else "scaled_close"
    )
    factor_params = {} if hasattr(indicator, "alpha_id") else {"scale": 2.0}
    spec = FactorSpec(
        name=factor_name,
        indicator=indicator,
        panel_line="factor",
        params=factor_params,
        field_bindings={"close": "feed:target:close"},
        direction=-1,
        mode=mode,
    )
    plan = LiveFactorPlan(
        targets=("A",),
        groups={"A": "primary"},
        factors={factor_name: spec},
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=min(30, count),
        max_pending_slots=2,
        max_window_bars=count,
        wait_timeout_ns=60_000_000_000,
        max_live_bar_age_seconds=max_live_bar_age_seconds,
        max_future_skew_seconds=max_future_skew_seconds,
    )
    if clock is None:
        clock = ReplayClock(
            [bar["available_at"] for bar in historical + live],
            now=start,
        )
    if activated:
        cerebro.add_live_bar_cohort(cohort, clock=clock)
        cerebro.addstrategy(OrdinaryStrategy, plan=plan, cohort=cohort)
    return cerebro, cohort, feed, plan, values, clock


@pytest.mark.parametrize("mode", ("native", "build"))
def test_ordinary_strategy_binds_real_cohort_feed_and_publishes_bounded_immutable_snapshot(
    mode,
):
    cerebro, cohort, feed, plan, values, clock = _make_inputs(mode=mode)

    strategy = cerebro.run()[0]

    assert len(strategy.snapshots) == len(values)
    assert all(snapshot.batch_complete for snapshot in strategy.snapshots)
    first = strategy.snapshots[0]
    assert first.readiness is LiveFactorReadiness.WARMUP
    assert (
        first.factors["scaled_close"].values["A"].status is LiveFactorOutputStatus.OUTPUT_AVAILABLE
    )
    assert first.factors["scaled_close"].values["A"].source_role == "history"
    snapshot = strategy.snapshots[-1]
    assert snapshot.readiness is LiveFactorReadiness.LIVE_READY
    assert snapshot.epoch_id == 7 and type(snapshot.epoch_id) is int
    assert snapshot.close_time == START + timedelta(minutes=len(values))
    assert snapshot.available_at == snapshot.close_time
    factor = snapshot.factors["scaled_close"]
    output = factor.values["A"]
    assert output.value == values[-1] * 2.0
    assert output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE
    assert output.source_role == "live"
    assert output.sequence == len(values)
    assert output.source_ref == "feed-A"
    assert factor.mode == mode
    assert factor.direction == -1
    assert factor.inputs["close"][0].line_name == "close"
    assert plan.max_live_bar_age_seconds == 60.0
    assert plan.max_future_skew_seconds == 0.0
    assert set(strategy.live_factors.factor_instances["scaled_close"]) == {"primary"}
    assert 0 < len(feed.close.array) <= 3
    assert len(clock.waits) > 0

    diagnostics = strategy.live_factors.factor_instances["scaled_close"][
        "primary"
    ].lifecycle_diagnostics
    assert diagnostics["diagnostic_kind"] == "bounded_live_samples"
    assert diagnostics["call_count"] == len(values)
    assert len(diagnostics["call_times"]) == 64
    assert diagnostics["call_times_truncated"] is True

    with pytest.raises(TypeError):
        snapshot.factors["other"] = factor
    with pytest.raises(TypeError):
        factor.values["other"] = output
    with pytest.raises((AttributeError, TypeError)):
        output.value = 0.0
    with pytest.raises(TypeError):
        plan.groups["A"] = "mutated"
    with pytest.raises(TypeError):
        plan.factors["other"] = plan.factors["scaled_close"]

    # A later mutation of a consumed line must not be projected as the old batch.
    feed.close[0] = -1.0
    degraded = strategy.live_factors.snapshot()
    assert degraded.readiness is LiveFactorReadiness.DEGRADED
    assert "feed_line_value_mismatch" in degraded.readiness_reasons
    assert degraded.factors["scaled_close"].values == MappingProxyType({})
    assert not hasattr(snapshot, "execution_permission")
    assert live_source_binding_active() is False


@pytest.mark.parametrize("mode", ("native", "build"))
def test_alpha001_panel_child_bind_inherits_only_the_active_factor_context(mode):
    cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(
        count=32,
        mode=mode,
        indicator=get_alpha(1),
    )

    strategy = cerebro.run()[0]
    factor = strategy.live_factors.factor_instances["alpha001"]["primary"]
    context = factor._factor_strict_context

    assert context.factor == "alpha001"
    assert context.failed is False
    assert strategy.snapshots
    rank_nodes = [node for node in factor._nodes.values() if isinstance(node, CrossSectionalRank)]
    assert len(rank_nodes) == 1
    assert rank_nodes[0]._factor_strict_context is context
    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert cohort.current_delivery(feed) is batch.receipt_for_feed(feed)
    assert live_source_binding_active() is False


def test_nested_live_bind_requires_explicit_factor_name_to_match_parent_context():
    _cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(count=2)
    strategy = _cerebro.run()[0]
    parent = strategy.live_factors.factor_instances["scaled_close"]["primary"]
    receipt = cohort.require_factor_field(feed, "close")

    def bind_child(factor_name):
        return CrossSectionalRank._bind_for_research(
            feed,
            output_datas=(feed,),
            asset_names=("A",),
            factor_name=factor_name,
            field_bindings={},
            research=None,
            mode="native",
            available_datas=(feed,),
            strict=True,
            line_inputs=(parent.outputs[feed].factor,),
            members=(None,),
            groups=("primary",),
        )

    with OwnerContext.set_owner(parent), live_source_binding_scope(
        cohort,
        ((feed, "close", receipt),),
    ):
        child = bind_child("scaled_close")
        assert child._factor_strict_context is parent._factor_strict_context
        with pytest.raises(ResearchConfigError, match="must match its parent factor_name"):
            bind_child("other_factor")


def test_old_live_bar_does_not_become_fresh_when_scheduler_time_advances():
    cerebro, _cohort, _feed, _plan, _values, clock = _make_inputs(
        count=1,
        max_live_bar_age_seconds=5.0,
        max_future_skew_seconds=1.0,
    )
    strategy = cerebro.run()[0]
    original = strategy.snapshots[-1]
    assert original.readiness is LiveFactorReadiness.LIVE_READY

    clock.now = original.close_time + timedelta(seconds=6)
    later = strategy.live_factors.snapshot()

    output = later.factors["scaled_close"].values["A"]
    assert later.readiness is LiveFactorReadiness.WARMUP
    assert "live_bar_stale" in later.readiness_reasons
    assert later.close_time == original.close_time
    assert later.available_at == original.available_at
    assert later.close_time != clock.now
    assert output.value == original.factors["scaled_close"].values["A"].value
    assert output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE


def test_future_close_time_exceeding_profile_blocks_readiness_but_keeps_output():
    cerebro, _cohort, _feed, _plan, _values, clock = _make_inputs(
        count=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=2.0,
    )
    strategy = cerebro.run()[0]
    original = strategy.snapshots[-1]
    clock.now = original.close_time - timedelta(seconds=3)

    future = strategy.live_factors.snapshot()

    output = future.factors["scaled_close"].values["A"]
    assert future.readiness is LiveFactorReadiness.WARMUP
    assert "live_bar_future_skew_exceeded" in future.readiness_reasons
    assert future.close_time == original.close_time
    assert future.available_at == original.available_at
    assert output.value == original.factors["scaled_close"].values["A"].value
    assert output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE


def test_future_available_at_exceeding_profile_blocks_readiness():
    cerebro, _cohort, _feed, _plan, _values, clock = _make_inputs(
        count=1,
        availability_delay_seconds=5.0,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=1.0,
    )
    strategy = cerebro.run()[0]
    original = strategy.snapshots[-1]
    assert original.available_at == original.close_time + timedelta(seconds=5)
    clock.now = original.close_time

    future = strategy.live_factors.snapshot()

    assert future.readiness is LiveFactorReadiness.WARMUP
    assert "live_bar_future_skew_exceeded" in future.readiness_reasons
    assert future.close_time == original.close_time
    assert future.available_at == original.available_at
    output = future.factors["scaled_close"].values["A"]
    assert output.value == original.factors["scaled_close"].values["A"].value
    assert output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE


def test_history_batch_stays_warmup_after_later_processing_time():
    cerebro, _cohort, _feed, _plan, _values, clock = _make_inputs(
        count=1,
        include_live=False,
        max_live_bar_age_seconds=1.0,
    )
    strategy = cerebro.run()[0]
    original = strategy.snapshots[-1]
    assert original.readiness is LiveFactorReadiness.WARMUP
    assert original.factors["scaled_close"].values["A"].status is (
        LiveFactorOutputStatus.OUTPUT_AVAILABLE
    )
    clock.now = original.close_time + timedelta(days=1)

    later = strategy.live_factors.snapshot()

    assert later.readiness is LiveFactorReadiness.WARMUP
    assert "live_bar_stale" not in later.readiness_reasons
    assert later.close_time == original.close_time
    assert later.available_at == original.available_at
    assert later.factors["scaled_close"].values["A"].status is (
        LiveFactorOutputStatus.OUTPUT_AVAILABLE
    )


def test_live_snapshot_fails_closed_when_injected_scheduler_clock_breaks():
    cerebro, _cohort, _feed, _plan, _values, clock = _make_inputs(count=1)
    strategy = cerebro.run()[0]
    original = strategy.snapshots[-1]
    clock.utc_now = lambda: datetime(2026, 10, 20, 9, 31)

    broken = strategy.live_factors.snapshot()

    assert broken.readiness is LiveFactorReadiness.WARMUP
    assert "scheduler_clock_unavailable" in broken.readiness_reasons
    assert broken.close_time == original.close_time
    assert broken.available_at == original.available_at
    output = broken.factors["scaled_close"].values["A"]
    assert output.value == original.factors["scaled_close"].values["A"].value
    assert output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE


@pytest.mark.parametrize(
    "value",
    (0, -1, True, None, float("inf"), float("nan"), "1"),
)
def test_live_plan_requires_a_finite_positive_bar_age(value):
    with pytest.raises(ResearchConfigError, match="max_live_bar_age_seconds"):
        _make_inputs(count=1, max_live_bar_age_seconds=value)


@pytest.mark.parametrize(
    "value",
    (-0.1, True, None, float("inf"), float("nan"), "0"),
)
def test_live_plan_requires_finite_nonnegative_future_skew(value):
    with pytest.raises(ResearchConfigError, match="max_future_skew_seconds"):
        _make_inputs(count=1, max_future_skew_seconds=value)


def test_live_snapshot_uses_normal_datetime_now_utc_scheduler_clock():
    captured_now = datetime.now(UTC).replace(microsecond=0)
    start = captured_now - timedelta(minutes=1, seconds=5)
    cerebro, _cohort, feed, _plan, _values, _clock = _make_inputs(
        count=1,
        start=start,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=0.0,
        clock=WallClock(),
    )

    strategy = cerebro.run()[0]
    snapshot = strategy.snapshots[-1]

    assert snapshot.readiness is LiveFactorReadiness.LIVE_READY
    assert snapshot.close_time == start + timedelta(minutes=1)
    assert snapshot.available_at == snapshot.close_time
    assert snapshot.close_time < datetime.now(UTC)
    assert feed.datetime.datetime(0) == snapshot.close_time.replace(tzinfo=None)


def test_schema_registration_without_cerebro_activation_cannot_bind_live_factors():
    cerebro, cohort, feed, plan, _values, _clock = _make_inputs(activated=False)

    with pytest.raises(ResearchConfigError, match="activated by Cerebro"):
        LiveFactorSet.bind(plan, {"A": feed}, cohort=cohort)

    cerebro.add_live_bar_cohort(cohort, clock=ReplayClock(()))
    cerebro.addstrategy(OrdinaryStrategy, plan=plan, cohort=cohort)
    strategy = cerebro.run()[0]
    assert strategy.live_factors.cohort is cohort


def test_factor_instances_and_snapshots_are_isolated_between_strategy_runs():
    first_cerebro, _first_cohort, _first_feed, _first_plan, _values, _clock = _make_inputs(
        count=2,
        base=100.0,
    )
    second_cerebro, _second_cohort, _second_feed, _second_plan, _values, _clock = _make_inputs(
        count=2,
        base=1_000.0,
    )

    first = first_cerebro.run()[0]
    second = second_cerebro.run()[0]

    first_factor = first.live_factors.factor_instances["scaled_close"]["primary"]
    second_factor = second.live_factors.factor_instances["scaled_close"]["primary"]
    assert first_factor is not second_factor
    assert first.snapshots[-1].factors["scaled_close"].values["A"].value == 202.0
    assert second.snapshots[-1].factors["scaled_close"].values["A"].value == 2_002.0
    assert first.snapshots[-1] is not second.snapshots[-1]
    assert live_source_binding_active() is False


def test_active_live_binding_rejects_public_factor_bind_without_context_name():
    _cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(count=1)
    receipt = cohort.require_factor_field(feed, "close")

    with live_source_binding_scope(cohort, ((feed, "close", receipt),)), pytest.raises(
        ResearchConfigError, match="non-empty factor_name"
    ):
        ScaledClose.bind(feed, mode="native", scale=2.0)


@pytest.mark.parametrize(
    ("strict", "factor_name", "message"),
    (
        (False, "scaled_close", "requires strict=True"),
        (True, None, "non-empty factor_name"),
        (True, "", "non-empty factor_name"),
        (True, "   ", "non-empty factor_name"),
        (True, 7, "non-empty factor_name"),
    ),
)
def test_active_live_binding_rejects_strict_or_factor_name_escape(strict, factor_name, message):
    _cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(count=1)
    receipt = cohort.require_factor_field(feed, "close")

    with live_source_binding_scope(cohort, ((feed, "close", receipt),)), pytest.raises(
        ResearchConfigError, match=message
    ):
        ScaledClose._bind_for_research(
            feed,
            output_datas=(feed,),
            asset_names=("A",),
            factor_name=factor_name,
            field_bindings={"close": "feed:target:close"},
            research=None,
            mode="native",
            available_datas=(feed,),
            strict=strict,
            scale=2.0,
        )


@pytest.mark.parametrize("mode", ("native", "build"))
def test_ordinary_live_factor_runtime_errors_keep_factor_context_and_cause(mode):
    cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(
        count=1,
        mode=mode,
        indicator=FailingLiveFactor,
    )

    with pytest.raises(FactorComputationError) as caught:
        cerebro.run()

    error = caught.value
    assert error.code == "FACTOR_COMPUTATION_FAILED"
    assert error.factor == "scaled_close"
    assert error.asset == "A"
    assert error.phase == "next"
    assert isinstance(error.__cause__, LookupError)
    assert str(error.__cause__) == "synthetic live factor runtime failure"

    # The error occurred after the exact source row passed cohort admission
    # and all feed lines advanced, so it is a factor runtime error rather than
    # a fabricated context for pre-factor source validation.
    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    receipt = batch.receipt_for_feed(feed)
    assert receipt.source_role == "live"
    assert cohort.current_delivery(feed) is receipt
    assert len(feed) == 1


def test_invalid_raw_live_event_is_rejected_before_feed_lines_and_strategy_callback():
    cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(
        count=1,
        bad_close=float("inf"),
    )

    with pytest.raises(LiveCohortValidationError):
        cerebro.run()

    assert cohort.current_batch() is None
    assert cohort.frozen is True
    assert len(feed) == 0


def test_snapshot_treats_an_unknown_operator_reason_as_unavailable():
    cerebro, _cohort, _feed, _plan, _values, _clock = _make_inputs(
        count=1,
        mode="build",
    )
    strategy = cerebro.run()[0]
    instance = strategy.live_factors.factor_instances["scaled_close"]["primary"]
    reason_line = instance._result_lines[0]._factor_research_reason_line
    reason_line[0] = 999

    output = strategy.live_factors.snapshot().factors["scaled_close"].values["A"]

    assert output.value == 200.0
    assert output.status is LiveFactorOutputStatus.OUTPUT_UNAVAILABLE
    assert output.reason == "UNKNOWN_REASON"


def test_custom_nan_without_reason_stays_unknown_even_when_inputs_are_live_ready():
    cerebro, _cohort, _feed, _plan, _values, _clock = _make_inputs(
        count=2, indicator=UnexplainedNaN, mode="native"
    )

    snapshot = cerebro.run()[0].snapshots[-1]
    output = snapshot.factors["scaled_close"].values["A"]

    assert snapshot.readiness is LiveFactorReadiness.LIVE_READY
    assert output.present and output.complete and output.quality == "GOOD"
    assert math.isnan(output.value)
    assert output.status is LiveFactorOutputStatus.OUTPUT_UNAVAILABLE
    assert output.reason is None  # No producer evidence permits inventing a cause.
    assert not hasattr(snapshot, "execution_permission")


@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runonce", (False, True))
def test_live_diagnostic_cap_does_not_truncate_offline_factor_coverage(mode, runonce):
    grid = pd.date_range(START, periods=96, freq="min", name="close_time")
    closes = [100.0 + index for index in range(len(grid))]
    source = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(grid),
        },
        index=grid,
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": grid - pd.Timedelta(minutes=1)}, index=grid),
        start=grid[0],
        end=grid[-1],
        targets=("A",),
        source_timezone="UTC",
        snapshot_id="offline-diagnostic-coverage",
        price_basis="unadjusted close",
        calendar_id="minute-fixture",
        frequency="1min",
    )
    spec = FactorSpec(
        name="scaled_close",
        indicator=ScaledClose,
        panel_line="factor",
        params={"scale": 2.0},
        field_bindings={"close": "feed:target:close"},
        mode=mode,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(align_to_grid(source, research, "A").feed, name="A")
    cerebro.addstrategy(FactorStrategy, research=research, factors={"scaled_close": spec})

    strategy = cerebro.run(runonce=runonce)[0]
    diagnostics = strategy.factor_instances["scaled_close"].lifecycle_diagnostics
    expected_times = tuple(grid.to_pydatetime())
    assert diagnostics["coverage_times"] == expected_times
    assert diagnostics["coverage_count"] == len(grid) > 64
    assert diagnostics["coverage_matches"] is True
    assert diagnostics.get("call_times_truncated", False) is False
    panel = strategy.get_panel()
    assert len(panel.factors) == len(grid)
    assert panel.factors["scaled_close"].tolist() == [value * 2.0 for value in closes]


def test_live_source_scope_does_not_skip_raw_dataframe_infinity_scan():
    frame = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [float("inf")], "volume": [1.0]},
        index=pd.DatetimeIndex([START + timedelta(minutes=1)]),
    )
    feed = bt.feeds.PandasData(dataname=frame)
    feed._name = "A"
    slot = LiveCalendarSlot(
        "slot-0",
        START,
        START + timedelta(minutes=1),
        "2026-10-20",
        "regular",
    )
    cohort = LiveBarCohort(
        "cohort-table",
        LiveCohortCalendar(
            calendar_id="calendar-table",
            version="v1",
            epoch_id=1,
            frequency="1min",
            frequency_seconds=60,
            timezone_id="UTC",
            clock_domain_id="clock-A",
            session_semantics="session-v1",
            slots=(slot,),
        ),
    )
    cohort.register_member(
        "member-A",
        feed,
        instrument="SYM",
        source_ref="frame-A",
        line_fields=("close",),
        raw_fields=("open", "high", "low", "close", "volume"),
        numeric_fields=("open", "high", "low", "close", "volume"),
    )
    receipt = cohort.require_factor_field(feed, "close")
    spec = FactorSpec(
        name="scaled_close",
        indicator=ScaledClose,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )

    with pytest.raises(FactorComputationError) as error, live_source_binding_scope(
        cohort,
        ((feed, "close", receipt),),
    ):
        spec.indicator._bind_for_research(
            feed,
            output_datas=(feed,),
            asset_names=("A",),
            factor_name=spec.name,
            field_bindings=spec.field_bindings,
            research=None,
            mode=spec.mode,
            available_datas=(feed,),
            strict=True,
            **dict(spec.params),
        )

    assert error.value.phase == "construct"
    assert error.value.__cause__ is not None
    assert "infinity" in str(error.value.__cause__).lower()


def test_live_source_scope_rejects_a_token_for_another_feed_object():
    cohort = LiveBarCohort(
        "cohort-A",
        LiveCohortCalendar(
            calendar_id="calendar-A",
            version="v1",
            epoch_id=1,
            frequency="1min",
            frequency_seconds=60,
            timezone_id="UTC",
            clock_domain_id="clock-A",
            session_semantics="session-v1",
            slots=(
                LiveCalendarSlot(
                    "slot-0",
                    START,
                    START + timedelta(minutes=1),
                    "2026-10-20",
                    "regular",
                ),
            ),
        ),
    )
    feed = object()
    cohort.register_member(
        "member-A",
        feed,
        instrument="SYM",
        source_ref="feed-A",
        line_fields=("close",),
        raw_fields=("open", "high", "low", "close", "volume"),
    )
    receipt = cohort.require_factor_field(feed, "close")

    with pytest.raises(ValueError, match="does not match"), live_source_binding_scope(
        cohort, ((object(), "close", receipt),)
    ):
        pass
