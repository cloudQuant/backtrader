"""Actual cohort composition for benchmark, capitalization and industry PIT fields."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import (
    FactorHistoryContract,
    FactorIndicator,
    FactorSpec,
    FieldPITPolicy,
    LiveFactorPlan,
    LiveFactorSet,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveFieldContract,
    LiveFieldObservation,
)


UTC = timezone.utc
START = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)
TARGETS = ("A", "B")
BENCHMARK = "benchmark"
_STANDARD_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_FIELD_UNITS = {
    "benchmark_close": ("benchmark-price", "USD/share"),
    "cap": ("cap-source", "USD"),
    "industry": ("industry-source", "industry-code:taxonomy-v1"),
}


class ReplayClock:
    def __init__(self, available_times):
        self.now = min(available_times)
        self.monotonic = 1_000
        self.available_times = tuple(sorted(available_times))

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        future = [value for value in self.available_times if value > self.now]
        elapsed = max(0.0, float(timeout_seconds))
        if future:
            elapsed = min(elapsed, (future[0] - self.now).total_seconds())
        self.now += timedelta(seconds=elapsed)
        self.monotonic += max(1, int(elapsed * 1_000_000_000))


class AuxiliaryFieldsValue(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("benchmark_close", "cap", "industry")
    lookback_h = 0
    history_contract = FactorHistoryContract.finite_window(span_bars=2)

    def __init__(self):
        super().__init__()
        self._input_lines = tuple(self.field_lines(alias) for alias in self.formula_fields)

    def next(self):
        for target, benchmark, cap, industry in zip(self.datas, *self._input_lines):
            self.outputs[target].factor[0] = benchmark[0] + cap[0] + industry[0]


class AuxiliaryFieldsStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.captured = []

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.captured.append((batch.slot_index, self.live_factors.snapshot(), batch))


def _observation(field, close_time, index, *, expired):
    source_ref, unit = _FIELD_UNITS[field]
    effective_at = close_time - timedelta(seconds=2 + index)
    available_at = close_time - timedelta(seconds=1 if index < 3 else 3)
    return LiveFieldObservation(
        source_ref=source_ref,
        unit=unit,
        effective_at=effective_at,
        available_at=available_at,
        revision=f"{field}-revision-{index}",
        valid_until=(
            close_time - timedelta(seconds=1) if expired else close_time + timedelta(minutes=2)
        ),
    )


def _event(name, slot, index, *, shift_future_benchmark):
    close_time = slot.close_time
    is_benchmark = name == BENCHMARK
    target_index = TARGETS.index(name) if not is_benchmark else None
    close = 100.0 + index if is_benchmark else 20.0 + 5.0 * target_index + index
    if is_benchmark and shift_future_benchmark and index >= 3:
        close += 1_000.0

    observations = {}
    values = {}
    if is_benchmark:
        observations["close"] = _observation(
            "benchmark_close", close_time, index, expired=(index == 2)
        )
    else:
        observations["cap"] = _observation(
            "cap", close_time, index, expired=(index == 2 and name == "B")
        )
        observations["industry"] = _observation(
            "industry", close_time, index, expired=(index == 2 and name == "A")
        )
        values.update(
            cap=1_000.0 + 250.0 * target_index + 10.0 * index,
            industry=11.0 + 100.0 * target_index,
        )

    return MappingProxyType(
        {
            "instrument": name,
            "symbol": name,
            "timestamp": close_time.timestamp(),
            "datetime": close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": close_time,
            "available_at": close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "auxiliary-pit-clock",
            "connection_generation": "generation-1",
            "bar_sequence": index + 1,
            "bar_id": f"{name}-{index + 1}",
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": float(index + 1),
            "openinterest": 0.0,
            **values,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "auxiliary-pit-fixture",
            "source_ref": f"bar-source-{name}",
            "field_observations": MappingProxyType(observations),
        }
    )


def _scenario(*, shift_future_benchmark):
    slots = tuple(
        LiveCalendarSlot(
            slot_id=f"aux-slot-{index}",
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day=START.date().isoformat(),
            session_segment="regular",
        )
        for index in range(5)
    )
    calendar = LiveCohortCalendar(
        calendar_id="auxiliary-pit-calendar",
        version="v1",
        epoch_id=41,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="auxiliary-pit-clock",
        session_semantics="regular-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "auxiliary-pit-cohort",
        calendar,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=10_000_000_000,
    )
    feeds = {}
    member_names = (*TARGETS, BENCHMARK)
    contracts_by_member = {
        name: (
            {
                "cap": LiveFieldContract("cap-source", "USD", "independent"),
                "industry": LiveFieldContract(
                    "industry-source", "industry-code:taxonomy-v1", "independent"
                ),
            }
            if name in TARGETS
            else {"close": LiveFieldContract("benchmark-price", "USD/share", "independent")}
        )
        for name in member_names
    }

    for name in member_names:
        extra_fields = ("cap", "industry") if name in TARGETS else ()
        line_fields = (*_STANDARD_FIELDS, *extra_fields)
        events = tuple(
            _event(name, slot, index, shift_future_benchmark=shift_future_benchmark)
            for index, slot in enumerate(slots)
        )
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=(),
            live_bars=events,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        feeds[name] = feed
        cohort.register_member(
            f"member-{name}",
            feed,
            instrument=name,
            source_ref=f"bar-source-{name}",
            line_fields=line_fields,
            raw_fields=line_fields,
            numeric_fields=line_fields,
            field_contracts=contracts_by_member[name],
        )

    bindings = {
        "benchmark_close": "feed:benchmark:close",
        "cap": "feed:target:cap",
        "industry": "feed:target:industry",
    }
    policies = {
        "benchmark_close": FieldPITPolicy("USD/share", 60.0),
        "cap": FieldPITPolicy("USD", 60.0),
        "industry": FieldPITPolicy("industry-code:taxonomy-v1", 60.0),
    }
    plan = LiveFactorPlan(
        targets=TARGETS,
        groups=dict.fromkeys(TARGETS, "market"),
        factors={
            "auxiliary_fields": FactorSpec(
                name="auxiliary_fields",
                indicator=AuxiliaryFieldsValue,
                panel_line="factor",
                field_bindings=bindings,
                field_policies=policies,
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=2,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=10_000_000_000,
        max_live_bar_age_seconds=120.0,
        max_future_skew_seconds=0.0,
    )
    clock = ReplayClock(tuple(slot.close_time for slot in slots))
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    for name in member_names:
        cerebro.adddata(feeds[name], name=name)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(AuxiliaryFieldsStrategy, plan=plan, cohort=cohort)
    return cerebro, plan, feeds


def _by_slot(strategy):
    return {slot: (snapshot, batch) for slot, snapshot, batch in strategy.captured}


def _field_rows(output):
    return {
        (row.alias, row.feed_name): row for rows in output.field_provenance.values() for row in rows
    }


@pytest.mark.integration
def test_auxiliary_benchmark_cap_and_industry_pit_expiry_preserve_targets_and_recover():
    baseline_cerebro, baseline_plan, _baseline_feeds = _scenario(shift_future_benchmark=False)
    changed_cerebro, changed_plan, _changed_feeds = _scenario(shift_future_benchmark=True)
    baseline = _by_slot(baseline_cerebro.run()[0])
    changed = _by_slot(changed_cerebro.run()[0])

    assert baseline_plan.targets == changed_plan.targets == TARGETS
    assert set(baseline) == set(changed) == set(range(5))
    for slot_index in range(3):
        base_snapshot, base_batch = baseline[slot_index]
        changed_snapshot, changed_batch = changed[slot_index]
        base_result = base_snapshot.factors["auxiliary_fields"]
        changed_result = changed_snapshot.factors["auxiliary_fields"]
        assert set(base_result.values) == set(changed_result.values) == set(TARGETS)
        for target in TARGETS:
            base_output = base_result.values[target]
            changed_output = changed_result.values[target]
            assert base_output.status is changed_output.status
            if math.isnan(base_output.value):
                assert math.isnan(changed_output.value)
            else:
                assert changed_output.value == pytest.approx(base_output.value)
        base_benchmark = base_batch.receipt_for_feed(_baseline_feeds["benchmark"])
        changed_benchmark = changed_batch.receipt_for_feed(_changed_feeds["benchmark"])
        assert base_benchmark.raw_values["close"] == changed_benchmark.raw_values["close"]
        assert (
            base_benchmark.envelope.field_observations["close"]
            == changed_benchmark.envelope.field_observations["close"]
        )

    expired_snapshot, expired_batch = baseline[2]
    expired_result = expired_snapshot.factors["auxiliary_fields"]
    assert expired_result.pit_policy_complete is True
    assert expired_result.pit_qualified is False
    assert set(expired_result.values) == set(TARGETS)
    assert all(
        output.status.value == "OUTPUT_UNAVAILABLE" for output in expired_result.values.values()
    )
    rows = _field_rows(expired_result.values["A"])
    assert rows[("benchmark_close", BENCHMARK)].status == "FIELD_EXPIRED"
    assert rows[("cap", "B")].status == "FIELD_EXPIRED"
    assert rows[("industry", "A")].status == "FIELD_EXPIRED"
    benchmark_receipt = expired_batch.receipt_for_feed(_baseline_feeds[BENCHMARK])
    cap_receipt = expired_batch.receipt_for_feed(_baseline_feeds["B"])
    industry_receipt = expired_batch.receipt_for_feed(_baseline_feeds["A"])
    assert benchmark_receipt.raw_values["close"] > 0.0
    assert math.isnan(benchmark_receipt.line_values["close"])
    assert cap_receipt.raw_values["cap"] > 0.0
    assert math.isnan(cap_receipt.line_values["cap"])
    assert math.isfinite(industry_receipt.raw_values["industry"])
    assert math.isnan(industry_receipt.line_values["industry"])

    # One clean row still carries the expired row in each two-bar dependency window.
    for result_snapshot, _batch in (baseline[3], changed[3]):
        result = result_snapshot.factors["auxiliary_fields"]
        assert result.pit_qualified is False
        assert set(result.values) == set(TARGETS)
        assert all(output.status.value == "OUTPUT_UNAVAILABLE" for output in result.values.values())

    base_recovered, base_batch = baseline[4]
    changed_recovered, changed_batch = changed[4]
    base_result = base_recovered.factors["auxiliary_fields"]
    changed_result = changed_recovered.factors["auxiliary_fields"]
    assert base_recovered.readiness.value == changed_recovered.readiness.value == "LIVE_READY"
    assert base_result.pit_qualified is changed_result.pit_qualified is True
    assert set(base_result.values) == set(changed_result.values) == set(TARGETS)
    for target in TARGETS:
        assert base_result.values[target].status.value == "OUTPUT_AVAILABLE"
        assert changed_result.values[target].status.value == "OUTPUT_AVAILABLE"
        assert changed_result.values[target].value - base_result.values[
            target
        ].value == pytest.approx(1_000.0)

    base_rows = _field_rows(base_result.values["A"])
    assert base_rows[("benchmark_close", BENCHMARK)].unit == "USD/share"
    assert (
        base_rows[("benchmark_close", BENCHMARK)].effective_at
        == base_batch.receipt_for_feed(_baseline_feeds["benchmark"])
        .envelope.field_observations["close"]
        .effective_at
    )
    assert base_rows[("benchmark_close", BENCHMARK)].available_at == (
        base_batch.receipt_for_feed(_baseline_feeds["benchmark"])
        .envelope.field_observations["close"]
        .available_at
    )
    assert base_rows[("cap", "A")].unit == "USD"
    assert base_rows[("industry", "A")].unit == "industry-code:taxonomy-v1"
    assert base_rows[("cap", "A")].effective_at == START + timedelta(minutes=5, seconds=-6)
    assert base_rows[("cap", "A")].available_at == START + timedelta(minutes=5, seconds=-3)
    prior_cap_row = _field_rows(baseline[3][0].factors["auxiliary_fields"].values["A"])[
        ("cap", "A")
    ]
    assert prior_cap_row.effective_at != base_rows[("cap", "A")].effective_at
    assert prior_cap_row.available_at != base_rows[("cap", "A")].available_at

    # The benchmark is an input member, while outputs and cross-section remain target-only.
    benchmark_inputs = base_result.inputs["benchmark_close"]
    assert tuple(item.feed_name for item in benchmark_inputs) == (BENCHMARK,)
    assert set(base_result.values) == set(TARGETS)
