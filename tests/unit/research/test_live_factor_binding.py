"""Strict ordinary-Strategy contracts for cohort-bound factor graphs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError, ResearchConfigError
from backtrader.research import (
    FactorIndicator,
    FactorSpec,
    LiveFactorPlan,
    LiveFactorOutputStatus,
    LiveFactorReadiness,
    LiveFactorSet,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)
from backtrader.research.strict import live_source_binding_active, live_source_binding_scope


UTC = timezone.utc
START = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


class ReplayClock:
    """Deterministic source clock that advances only to scheduled availability."""

    def __init__(self, available_times):
        self.now = START
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


def _bar(slot, sequence, close, source_role):
    return MappingProxyType(
        {
            "instrument": "SYM",
            "symbol": "SYM",
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time,
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


def _make_inputs(*, count=70, mode="native", activated=True, bad_close=None, base=100.0):
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-%d" % index,
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2026-10-20",
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
    historical = tuple(
        _bar(slot, index + 1, values[index], "history")
        for index, slot in enumerate(slots[:-1])
    )
    live = (_bar(slots[-1], count, values[-1], "live"),)
    feed = bt.feeds.BtApiFeed(
        dataname="SYM",
        historical_bars=historical,
        live_bars=live,
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
    spec = FactorSpec(
        name="scaled_close",
        indicator=ScaledClose,
        panel_line="factor",
        params={"scale": 2.0},
        field_bindings={"close": "feed:target:close"},
        direction=-1,
        mode=mode,
    )
    plan = LiveFactorPlan(
        targets=("A",),
        groups={"A": "primary"},
        factors={"scaled_close": spec},
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=min(30, count),
        max_pending_slots=2,
        max_window_bars=count,
        wait_timeout_ns=60_000_000_000,
    )
    clock = ReplayClock([bar["available_at"] for bar in historical + live])
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
    assert first.factors["scaled_close"].values["A"].status is LiveFactorOutputStatus.OUTPUT_AVAILABLE
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
    assert set(strategy.live_factors.factor_instances["scaled_close"]) == {"primary"}
    assert 0 < len(feed.close.array) <= 3
    assert len(clock.waits) > 0

    diagnostics = strategy.live_factors.factor_instances["scaled_close"]["primary"].lifecycle_diagnostics
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
