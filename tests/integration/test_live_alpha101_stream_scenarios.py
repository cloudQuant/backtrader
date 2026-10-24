"""All-101 live gap, future-causality, and finite-history scenarios.

The execution path in these tests is the ordinary Cerebro, BtApiFeed,
LiveBarCohort, and LiveFactorSet composition. Inputs are deterministic local
source events; expected Alpha101 values come from the existing independent
paper-formula reference and AST-backed trace validator.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError
from backtrader.research import (
    FactorHistoryContract,
    FactorSpec,
    LiveFactorPlan,
    LiveFactorSet,
)
from backtrader.research.alpha101 import get_alpha
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveSourceOrigin,
)
from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_live_cohort_harness import (
    AVAILABILITY_DELAY_SECONDS,
    BASE_LINE_FIELDS,
    BENCHMARK_NAME,
    CALENDAR_ID,
    CLOCK_DOMAIN_ID,
    FREQUENCY,
    FREQUENCY_SECONDS,
    MAX_PENDING_SLOTS,
    TARGET_LINE_FIELDS,
    TARGET_COUNT,
    WAIT_TIMEOUT_NS,
    WARMUP_BARS,
    FullGridFactorTraceView,
    ReplayClock,
    alpha_partitions,
    assert_evaluation_witness,
    field_bindings_for_alpha,
    materialize_live_presence_for_graph,
    positive_target_frames,
    _result_reason_name,
    _same_number,
)
from tests.test_utils.alpha101_native_harness import selection_is_focused
from tests.test_utils.alpha101_trace_validation import (
    _compare_matrices,
    _factor_graph_pair_records,
    validate_factor_trace,
)


UTC = timezone.utc
_GAP_INDEX = 450
_GAP_ROWS = 800
_CAUSAL_ROWS = 320
_CAUSAL_PREFIX_ROWS = 300
_REBUILD_ROWS = 320
# The exact 60-row suffix has finite, varying independent-oracle witnesses for all IDs.
_REBUILD_SUFFIX_ROWS = 60


def _same_cell(left: Any, right: Any) -> bool:
    """Compare fixture cells while treating matching NaNs as equal."""

    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError, OverflowError):
        return left == right
    if math.isnan(left_value) or math.isnan(right_value):
        return math.isnan(left_value) and math.isnan(right_value)
    return left_value == right_value


def _assert_snapshot_output_equal(left: Any, right: Any, *, label: str) -> None:
    """Compare paired snapshot outputs without collapsing value and readiness."""

    if not _same_number(float(left.value), float(right.value)):
        raise AssertionError("%s output values differ" % label)
    left_status = getattr(left.status, "value", left.status)
    right_status = getattr(right.status, "value", right.status)
    if (
        left_status != right_status
        or left.reason != right.reason
        or left.present is not right.present
        or left.complete is not right.complete
        or left.quality != right.quality
    ):
        raise AssertionError("%s output status/reason/quality differs" % label)


class _ScenarioCapture(bt.Strategy):
    """Capture whole-batch live snapshots, including complete missing rows."""

    params = (("cohort", None), ("plan", None), ("clock", None), ("planned_grid", None))

    def __init__(self) -> None:
        self.feed_by_name = {data._name: data for data in self.datas}
        self.live_factor_set = LiveFactorSet.bind(
            self.p.plan,
            self.feed_by_name,
            cohort=self.p.cohort,
        )
        self.readings = []
        self.line_lengths = []
        self.eligible_batches = []

    def _capture(self) -> None:
        batch = self.p.cohort.current_batch()
        if batch is None or batch.status != "COMPLETE":
            raise AssertionError("scenario callback ran without a complete planned cohort batch")
        if batch.close_time != self.p.planned_grid[len(self.readings)]:
            raise AssertionError("scenario callback skipped or compressed a planned grid slot")
        if len(batch.members) != len(self.feed_by_name):
            raise AssertionError("complete scenario batch omitted a registered feed")
        callback_time = self.p.clock.utc_now()

        lengths = tuple(len(feed) for feed in self.datas)
        if not lengths or len(set(lengths)) != 1:
            raise AssertionError("real BtApiFeed lines did not advance atomically")
        self.line_lengths.append(lengths)

        receipts = {}
        line_values = {}
        for name, feed in self.feed_by_name.items():
            receipt = batch.receipt_for_feed(feed)
            if receipt is None or receipt.feed_ref is not feed:
                raise AssertionError("scenario receipt does not bind its exact BtApiFeed")
            if receipt.close_time != batch.close_time or receipt.complete is not True:
                raise AssertionError("scenario receipt does not cover the exact completed slot")
            if receipt.available_at > callback_time:
                raise AssertionError("scenario callback ran before source availability")
            receipts[name] = receipt
            member = self.p.cohort.member_for_feed(feed)
            line_values[name] = {
                field: float(getattr(feed, field)[0]) for field in member.line_fields
            }
            raw_values = receipt.envelope.raw_values
            for field in member.line_fields:
                if field not in raw_values or not _same_cell(
                    line_values[name][field], raw_values[field]
                ):
                    raise AssertionError(
                        "BtApiFeed line %s.%s differs from its sealed source receipt"
                        % (name, field)
                    )
            if receipt.present is False:
                expected_missing = tuple(sorted(member.numeric_fields))
                if tuple(receipt.missing_fields) != expected_missing:
                    raise AssertionError(
                        "missing receipt does not name every declared numeric field"
                    )
                if receipt.envelope.quality_flags != ("MISSING_FIELDS",):
                    raise AssertionError("missing receipt lost its explicit missing-fields flag")
                if any(not math.isnan(line_values[name][field]) for field in expected_missing):
                    raise AssertionError("missing receipt advanced non-NaN numeric feed lines")
            elif receipt.envelope.quality_flags:
                raise AssertionError("present receipt carries a missing-field quality flag")

        snapshot = self.live_factor_set.snapshot()
        if (
            snapshot.batch_complete is not True
            or snapshot.batch_id != batch.batch_id
            or snapshot.close_time != batch.close_time
            or snapshot.available_at != batch.available_at
            or snapshot.available_at is None
            or snapshot.available_at > callback_time
        ):
            raise AssertionError("live snapshot does not bind the exact available current batch")
        outputs = {
            factor_name: dict(result.values) for factor_name, result in snapshot.factors.items()
        }
        for factor_name, target_values in outputs.items():
            result = snapshot.factors[factor_name]
            if tuple(target_values) != tuple(self.p.plan.targets):
                raise AssertionError("benchmark or feed order changed the factor target universe")
            for target, output in target_values.items():
                receipt = receipts[target]
                if (
                    output.present is not receipt.present
                    or output.complete is not receipt.complete
                    or output.quality != receipt.quality
                ):
                    raise AssertionError("snapshot quality metadata differs from its exact receipt")
                instance = self.live_factor_set.factor_instances[factor_name]["default"]
                feed = self.feed_by_name[target]
                line_value = float(instance.outputs[feed][result.panel_line][0])
                if not _same_number(float(output.value), line_value):
                    raise AssertionError("snapshot value differs from its ordinary factor line")
                line_reason = (
                    None
                    if isinstance(instance, (_RecursiveClose, _FiniteWindowClose))
                    else _result_reason_name(instance, feed, result.panel_line)
                )
                if output.reason != line_reason:
                    raise AssertionError(
                        "snapshot reason differs from its factor result reason line"
                    )
                expected_available = (
                    output.present is True
                    and output.complete is True
                    and output.quality == "GOOD"
                    and math.isfinite(float(output.value))
                    and line_reason is None
                )
                expected_status = "OUTPUT_AVAILABLE" if expected_available else "OUTPUT_UNAVAILABLE"
                if getattr(output.status, "value", output.status) != expected_status:
                    raise AssertionError("snapshot availability status differs from value/reason")

        record = {
            "batch_id": batch.batch_id,
            "close_time": batch.close_time,
            "available_at": batch.available_at,
            "callback_time": callback_time,
            "readiness": snapshot.readiness,
            "readiness_reasons": tuple(snapshot.readiness_reasons),
            "receipts": receipts,
            "cutovers": dict(batch.cutovers),
            "line_values": line_values,
            "outputs": outputs,
        }
        self.readings.append(record)
        if getattr(snapshot.readiness, "value", snapshot.readiness) == "LIVE_READY":
            self.eligible_batches.append(batch.batch_id)

    def prenext(self) -> None:
        self._capture()

    def nextstart(self) -> None:
        self._capture()

    def next(self) -> None:
        self._capture()

    def get_panel(self) -> Any:
        if not self.readings:
            raise AssertionError("scenario collected no live snapshots")
        targets = tuple(self.p.plan.targets)
        times = [record["close_time"] for record in self.readings]
        index = pd.MultiIndex.from_product([times, targets], names=("time", "asset"))
        columns = {}
        for factor_name in self.p.plan.factors:
            columns[factor_name] = [
                record["outputs"][factor_name][target].value
                for record in self.readings
                for target in targets
            ]
        return SimpleNamespace(
            factors=pd.DataFrame(columns, index=index, dtype="float64"),
            factor_order=tuple(self.p.plan.factors),
        )


class _FiniteWindowClose(FactorIndicator):
    # Finite custom factor with an authored three-row reconstruction contract.

    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 2
    history_contract = FactorHistoryContract.finite_window(span_bars=3)

    def __init__(self) -> None:
        super().__init__()
        self.addminperiod(3)
        self._close_lines = self.field_lines("close")

    def next(self) -> None:
        for data, close_line in zip(self._factor_target_datas, self._close_lines):
            if len(close_line) < 3:
                continue
            self.outputs[data].factor[0] = (
                float(close_line[0]) + float(close_line[-1]) + float(close_line[-2])
            ) / 3.0


class _TooShortFiniteWindowClose(_FiniteWindowClose):
    history_contract = FactorHistoryContract.finite_window(span_bars=2)


class _RecursiveClose(FactorIndicator):
    """Deliberately recursive fixture whose state cannot be bounded by H=0."""

    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0
    history_contract = FactorHistoryContract.replay_from_source_origin()

    def __init__(self) -> None:
        super().__init__()
        self._close_lines = self.field_lines("close")
        self._state_by_data = {id(data): 0.0 for data in self._factor_target_datas}

    def next(self) -> None:
        for data, close_line in zip(self._factor_target_datas, self._close_lines):
            state = 0.5 * self._state_by_data[id(data)] + float(close_line[0])
            self._state_by_data[id(data)] = state
            self.outputs[data].factor[0] = state


class _UnqualifiedRecursiveClose(_RecursiveClose):
    history_contract = None


def _targets_and_grid(
    frames: Mapping[str, pd.DataFrame]
) -> Tuple[Tuple[str, ...], Tuple[datetime, ...]]:
    targets = tuple(frames)
    if len(targets) != TARGET_COUNT:
        raise ValueError("stream scenarios require the established five target assets")
    first_grid = tuple(frames[targets[0]].index)
    if not first_grid:
        raise ValueError("stream scenario grid must not be empty")
    if any(tuple(frame.index) != first_grid for frame in frames.values()):
        raise ValueError("all scenario target frames must share the exact planned grid")
    grid = tuple(_as_utc(point) for point in first_grid)
    if any(
        (right - left).total_seconds() != FREQUENCY_SECONDS for left, right in zip(grid, grid[1:])
    ):
        raise ValueError("stream scenario grid must advance in exact UTC days")
    return targets, grid


def _as_utc(point: Any) -> datetime:
    if hasattr(point, "to_pydatetime"):
        point = point.to_pydatetime()
    if point.tzinfo is None or point.utcoffset() is None:
        raise AssertionError("scenario fixture times must be timezone-aware")
    return point.astimezone(UTC)


def _slots(grid: Sequence[datetime]) -> Tuple[LiveCalendarSlot, ...]:
    return tuple(
        LiveCalendarSlot(
            slot_id="alpha101-scenario-%06d" % index,
            bucket_start=close_time - timedelta(seconds=FREQUENCY_SECONDS),
            close_time=close_time,
            trading_day=close_time.date().isoformat(),
            session_segment="regular",
        )
        for index, close_time in enumerate(grid)
    )


def _events_for(
    name: str,
    slots: Sequence[LiveCalendarSlot],
    frame: Optional[pd.DataFrame],
    *,
    availability_delay_seconds: int,
    gap_target: Optional[str],
    gap_index: Optional[int],
    future_available_from: Optional[int],
) -> Tuple[Mapping[str, Any], ...]:
    from tests.test_utils.alpha101_live_cohort_harness import _slot_events

    declared = TARGET_LINE_FIELDS if frame is not None else BASE_LINE_FIELDS
    rows = []
    for index, source_event in enumerate(_slot_events(name, slots, frame)):
        event = dict(source_event)
        event["available_at"] = slots[index].close_time + timedelta(
            seconds=availability_delay_seconds
        )
        if future_available_from is not None and index >= future_available_from:
            # A different source arrival time is evidence about a future row;
            # it must never rewrite a previously sealed prefix.
            event["available_at"] = slots[index].close_time + timedelta(seconds=9)
            if frame is None:
                old_open = float(event["open"])
                old_close = float(event["close"])
                future_open = old_open * 1.07 + index * 0.013
                future_close = old_close * 0.93 - index * 0.017
                event.update(
                    {
                        "open": future_open,
                        "close": future_close,
                        "high": max(future_open, future_close) + 2.1,
                        "low": min(future_open, future_close) - 1.4,
                        "volume": float(event["volume"]) * 1.31 + index * 41.0,
                        "openinterest": float(event["openinterest"]) + 313.0 + index,
                    }
                )
        if gap_target == name and gap_index == index:
            for field in declared:
                event[field] = math.nan
            event.update(
                {
                    "present": False,
                    "quality": "MISSING",
                    "quality_flags": ("MISSING_FIELDS",),
                    "missing_fields": tuple(sorted(declared)),
                }
            )
        rows.append(event)
    return tuple(MappingProxyType(row) for row in rows)


def _source_origins(
    frames: Mapping[str, pd.DataFrame],
    *,
    source_role: str,
) -> Mapping[str, LiveSourceOrigin]:
    # Build adapter declarations from the exact first immutable source rows.
    targets, grid = _targets_and_grid(frames)
    slots = _slots(grid)
    origins = {}
    for name in targets + (BENCHMARK_NAME,):
        frame = frames.get(name)
        events = _events_for(
            name,
            slots,
            frame,
            availability_delay_seconds=AVAILABILITY_DELAY_SECONDS,
            gap_target=None,
            gap_index=None,
            future_available_from=None,
        )
        first = events[0]
        source_ref = (
            "synthetic-target-%s" % name if frame is not None else "synthetic-named-benchmark-index"
        )
        origins[name] = LiveSourceOrigin(
            member_id="member-%s" % name,
            epoch_id=1,
            source_ref=source_ref,
            source_role=source_role,
            connection_generation=first["connection_generation"],
            bar_id=first["bar_id"],
            feed_sequence=first["bar_sequence"],
            close_time=first["bucket_end"],
        )
    return origins


def _run_live(
    frames: Mapping[str, pd.DataFrame],
    alpha_ids: Iterable[int] = (),
    *,
    factor_mode: str = "native",
    gap_target: Optional[str] = None,
    gap_index: Optional[int] = None,
    future_available_from: Optional[int] = None,
    availability_delay_seconds: int = AVAILABILITY_DELAY_SECONDS,
    feed_order: Optional[Sequence[str]] = None,
    history_count: Optional[int] = None,
    factor_specs: Optional[Mapping[str, FactorSpec]] = None,
    source_origins: Optional[Mapping[str, LiveSourceOrigin]] = None,
    reset_live_source_identity: bool = False,
    max_window_bars: Optional[int] = None,
    allow_history_prewarm: Optional[bool] = None,
    run_label: str = "scenario",
) -> Tuple[_ScenarioCapture, LiveBarCohort, ReplayClock, Tuple[datetime, ...]]:
    """Run real Feed/Cerebro/cohort/live-factor objects on local events."""

    targets, grid = _targets_and_grid(frames)
    slots = _slots(grid)
    member_names = targets + (BENCHMARK_NAME,)
    if feed_order is None:
        selected_feed_order = member_names
    else:
        selected_feed_order = tuple(feed_order)
        if set(selected_feed_order) != set(member_names) or len(selected_feed_order) != len(
            member_names
        ):
            raise ValueError("feed_order must permute all target and benchmark members")
    if history_count is not None and not 1 <= history_count <= len(slots):
        raise ValueError("history_count must select a non-empty finite prefix")

    window_limit = len(slots) if max_window_bars is None else max_window_bars
    if allow_history_prewarm is None:
        allow_history_prewarm = history_count is not None
    calendar = LiveCohortCalendar(
        calendar_id=CALENDAR_ID,
        version="v1",
        epoch_id=1,
        frequency=FREQUENCY,
        frequency_seconds=FREQUENCY_SECONDS,
        timezone_id="UTC",
        clock_domain_id=CLOCK_DOMAIN_ID,
        session_semantics="alpha101-synthetic-daily-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "alpha101-%s-%s-%d" % (run_label, factor_mode, len(slots)),
        calendar,
        max_pending_slots=MAX_PENDING_SLOTS,
        max_window_bars=window_limit,
        wait_timeout_ns=WAIT_TIMEOUT_NS,
    )
    clock = ReplayClock(grid[0] - timedelta(seconds=1))
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    for name in selected_feed_order:
        frame = frames.get(name)
        events = _events_for(
            name,
            slots,
            frame,
            availability_delay_seconds=availability_delay_seconds,
            gap_target=gap_target,
            gap_index=gap_index,
            future_available_from=future_available_from,
        )
        if history_count is None:
            historical_bars, live_bars = (), events
        else:
            historical_bars = events[:history_count]
            # Identical overlap is deliberately replayed through the live
            # source; the cohort must deduplicate it before the new live tail.
            live_bars = events[history_count - 1 :]
        if reset_live_source_identity:
            # Provider sequence/generation scope restarts at the live role;
            # planned calendar slots remain the cross-role identity.
            live_bars = tuple(
                MappingProxyType(
                    {
                        **dict(event),
                        "connection_generation": "alpha101-live-generation-2",
                        "bar_sequence": sequence,
                    }
                )
                for sequence, event in enumerate(live_bars, start=1)
            )
        source_ref = (
            "synthetic-target-%s" % name if frame is not None else "synthetic-named-benchmark-index"
        )
        source_origin = None if source_origins is None else source_origins.get(name)
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=historical_bars,
            live_bars=live_bars,
            cohort_source_mode=True,
            cohort_source_origin=source_origin,
            backfill_start=False,
            timeframe=bt.TimeFrame.Days,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        cerebro.adddata(feed, name=name)
        declared = TARGET_LINE_FIELDS if frame is not None else BASE_LINE_FIELDS
        cohort.register_member(
            "member-%s" % name,
            feed,
            instrument=name,
            source_ref=source_ref,
            source_origin=source_origin,
            line_fields=declared,
            raw_fields=declared + ("effective_at",),
            numeric_fields=declared,
        )

    if factor_specs is None:
        factors = {}
        for alpha_id in alpha_ids:
            factor_name = "alpha%d" % alpha_id
            indicator = get_alpha(alpha_id)
            factors[factor_name] = FactorSpec(
                name=factor_name,
                indicator=indicator,
                panel_line="factor",
                field_bindings=field_bindings_for_alpha(indicator),
                mode=factor_mode,
            )
    else:
        factors = dict(factor_specs)
    if not factors:
        raise ValueError("a scenario needs at least one production or recursive factor")

    plan = LiveFactorPlan(
        plan_id="alpha101-%s-%s" % (run_label, factor_mode),
        targets=targets,
        groups=dict.fromkeys(targets, "default"),
        factors=factors,
        calendar_id=CALENDAR_ID,
        frequency=FREQUENCY,
        warmup_min_bars=WARMUP_BARS,
        max_pending_slots=MAX_PENDING_SLOTS,
        max_window_bars=window_limit,
        wait_timeout_ns=WAIT_TIMEOUT_NS,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
        allow_history_prewarm=allow_history_prewarm,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _ScenarioCapture,
        cohort=cohort,
        plan=plan,
        clock=clock,
        planned_grid=grid,
    )
    strategy = cerebro.run()[0]
    if set(strategy.feed_by_name) != set(member_names):
        raise AssertionError("ordinary Strategy did not receive the exact target/benchmark set")
    return strategy, cohort, clock, grid


def _assert_contiguous_complete_grid(
    strategy: _ScenarioCapture,
    cohort: LiveBarCohort,
    grid: Sequence[datetime],
) -> None:
    if len(strategy.readings) != len(grid):
        raise AssertionError(
            "live path compressed or omitted planned slots: %d != %d"
            % (len(strategy.readings), len(grid))
        )
    if len(strategy.line_lengths) != len(grid):
        raise AssertionError("ordinary Strategy callback count differs from the full grid")
    for index, (record, point) in enumerate(zip(strategy.readings, grid)):
        if record["close_time"] != point:
            raise AssertionError("live snapshot close time differs from the planned grid")
        if record["available_at"] < point or record["available_at"] > record["callback_time"]:
            raise AssertionError("cohort callback violated the source-availability boundary")
        if record["callback_time"] - point > timedelta(seconds=30):
            raise AssertionError("live cohort callback exceeded its configured freshness window")
        if len(set(strategy.line_lengths[index])) != 1:
            raise AssertionError("feed line lengths diverged within a published cohort batch")
        if strategy.line_lengths[index][0] != index + 1:
            raise AssertionError("feed line cursor did not advance exactly one planned slot")
        if len(record["receipts"]) != len(strategy.feed_by_name):
            raise AssertionError("published batch omitted one or more exact feed receipts")
        for name, receipt in record["receipts"].items():
            if receipt.close_time != point or receipt.slot_index != index:
                raise AssertionError("receipt changed its planned slot identity")
            if receipt.complete is not True:
                raise AssertionError("a planned slot was not explicitly complete")
            if receipt.present is True:
                if receipt.quality != "GOOD" or receipt.missing_fields:
                    raise AssertionError("present slot carries a missing or blocking quality")
            else:
                if receipt.quality != "MISSING" or not receipt.missing_fields:
                    raise AssertionError("absent source slot lost its explicit missing contract")
                member = cohort.member_for_feed(strategy.feed_by_name[name])
                if tuple(receipt.missing_fields) != tuple(sorted(member.numeric_fields)):
                    raise AssertionError("absent source slot has an incomplete missing-field mask")
                if any(
                    not math.isnan(float(record_field))
                    for record_field in strategy.readings[index]["line_values"][name].values()
                ):
                    raise AssertionError("absent source slot contains a non-NaN feed field")
            if receipt.available_at > record["available_at"]:
                raise AssertionError("batch available_at precedes one of its member receipts")
        benchmark = record["receipts"][BENCHMARK_NAME]
        if (
            benchmark.source_ref != "synthetic-named-benchmark-index"
            or benchmark.close_time != point
            or BENCHMARK_NAME in strategy.p.plan.targets
        ):
            raise AssertionError("named benchmark provenance or target exclusion changed")
    batch = cohort.current_batch()
    if batch is None or batch.status != "COMPLETE" or batch.close_time != grid[-1]:
        raise AssertionError("scenario did not finish on the last complete planned batch")


def _trace_for(
    strategy: _ScenarioCapture,
    frames: Mapping[str, pd.DataFrame],
    alpha_ids: Sequence[int],
    grid: Sequence[datetime],
    *,
    panel_contract: str,
) -> Tuple[Dict[int, FullGridFactorTraceView], Dict[int, Mapping[str, Any]]]:
    traces = {}
    reports = {}
    assets = tuple(strategy.p.plan.targets)
    for alpha_id in alpha_ids:
        factor_name = "alpha%d" % alpha_id
        instance = strategy.live_factor_set.factor_instances[factor_name]["default"]
        diagnostics = instance.lifecycle_diagnostics
        if diagnostics["call_count"] != len(grid):
            raise AssertionError(
                "Alpha%d advanced %r times for %d planned slots"
                % (alpha_id, diagnostics["call_count"], len(grid))
            )
        sample = tuple(_as_utc(point) for point in diagnostics["call_times"])
        expected_sample = tuple(_as_utc(point) for point in grid[-len(sample) :]) if sample else ()
        if sample != expected_sample:
            raise AssertionError(
                "Alpha%d bounded callback sample differs from live batches" % alpha_id
            )
        if len(grid) > len(sample) and not diagnostics.get("call_times_truncated", False):
            raise AssertionError(
                "Alpha%d omitted its bounded callback truncation marker" % alpha_id
            )
        if diagnostics.get("coverage_count") != len(grid) or diagnostics.get("once_count") != 0:
            raise AssertionError(
                "Alpha%d live callback coverage is incomplete or duplicated" % alpha_id
            )
        for nested in FactorStrategy._factor_tree(instance):
            if isinstance(nested, FactorIndicator):
                nested_diagnostics = nested.lifecycle_diagnostics
                if nested_diagnostics["call_count"] != len(grid):
                    raise AssertionError(
                        "Alpha%d nested factor callback count is incomplete" % alpha_id
                    )
                nested_sample = tuple(_as_utc(point) for point in nested_diagnostics["call_times"])
                nested_expected = (
                    tuple(_as_utc(point) for point in grid[-len(nested_sample) :])
                    if nested_sample
                    else ()
                )
                if nested_sample != nested_expected:
                    raise AssertionError(
                        "Alpha%d nested callback sample differs from live batches" % alpha_id
                    )
        trace = FullGridFactorTraceView(instance, grid)
        report = validate_factor_trace(
            trace,
            alpha_id,
            frames,
            assets,
            grid,
            strategy=strategy,
            panel_contract=panel_contract,
        )
        if report["failures"]:
            raise AssertionError(
                "Alpha%d independent live trace failed: %r" % (alpha_id, report["failures"][:12])
            )
        if report["matched_nodes"] <= 0 or report["finite_witness"] is not True:
            raise AssertionError(
                "Alpha%d passed without matched nodes and finite values" % alpha_id
            )
        traces[alpha_id] = trace
        reports[alpha_id] = report
    return traces, reports


def _graph_segment_equal(
    left_factor: Any,
    right_factor: Any,
    alpha_id: int,
    *,
    left_slice: slice,
    right_slice: slice,
) -> Mapping[str, Any]:
    """Compare existing graph node values/reasons over a causal segment."""

    left = _factor_graph_pair_records(left_factor, alpha_id)
    right = _factor_graph_pair_records(right_factor, alpha_id)
    if left["assets"] != right["assets"] or left["root"] != right["root"]:
        raise AssertionError("Alpha%d graph asset identities or root AST changed" % alpha_id)
    if left["target_order"] != right["target_order"]:
        raise AssertionError("Alpha%d factor target order changed inside the scenario" % alpha_id)
    if left["grid"][left_slice] != right["grid"][right_slice]:
        raise AssertionError(
            "Alpha%d compared graph segments use different source times" % alpha_id
        )
    if set(left["nodes"]) != set(right["nodes"]):
        raise AssertionError("Alpha%d production node signatures changed" % alpha_id)

    compared_nodes = 0
    compared_value_cells = 0
    compared_reason_cells = 0
    for signature in left["nodes"]:
        left_records = list(left["nodes"][signature])
        right_records = list(right["nodes"][signature])
        if len(left_records) != len(right_records):
            raise AssertionError("Alpha%d node multiplicity changed for %r" % (alpha_id, signature))
        unmatched = list(right_records)
        for left_record in left_records:
            match_index = None
            for candidate_index, right_record in enumerate(unmatched):
                left_values = left_record["values"][left_slice]
                right_values = right_record["values"][right_slice]
                equal_values, _message = _compare_matrices(
                    left_values, right_values, exact=True, label="Alpha%d node values" % alpha_id
                )
                left_reasons = left_record["reasons"]
                right_reasons = right_record["reasons"]
                equal_reasons = False
                if left_reasons is not None and right_reasons is not None:
                    equal_reasons, _message = _compare_matrices(
                        left_reasons[left_slice],
                        right_reasons[right_slice],
                        exact=True,
                        label="Alpha%d node reasons" % alpha_id,
                    )
                if equal_values and equal_reasons:
                    match_index = candidate_index
                    compared_value_cells += sum(len(row) for row in left_values)
                    compared_reason_cells += sum(len(row) for row in left_reasons[left_slice])
                    break
            if match_index is None:
                raise AssertionError(
                    "Alpha%d value/reason node segment differs for %r" % (alpha_id, signature)
                )
            unmatched.pop(match_index)
            compared_nodes += 1

    if set(left["results"]) != set(right["results"]):
        raise AssertionError("Alpha%d final result target identities changed" % alpha_id)
    for asset in left["results"]:
        equal, message = _compare_matrices(
            left["results"][asset][left_slice],
            right["results"][asset][right_slice],
            exact=True,
            label="Alpha%d final result %s" % (alpha_id, asset),
        )
        if not equal:
            raise AssertionError(message)
    if compared_nodes <= 0 or compared_value_cells <= 0 or compared_reason_cells <= 0:
        raise AssertionError(
            "Alpha%d segment comparison did not cover graph values and reasons" % alpha_id
        )
    return {
        "matched_nodes": compared_nodes,
        "node_value_cells": compared_value_cells,
        "node_reason_cells": compared_reason_cells,
    }


def _materialize_presence_segment(strategy: _ScenarioCapture, start: int, stop: int) -> None:
    """Give the graph comparator receipt-backed presence for the compared rows."""

    materialize_live_presence_for_graph(strategy)
    for groups in strategy.live_factor_set.factor_instances.values():
        for instance in groups.values():
            for line in instance.formula_members:
                owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
                present = getattr(owner, "_present", None)
                if present is None or not 0 <= start <= stop <= len(present):
                    raise AssertionError("graph presence segment is not receipt-backed")
                owner._present = tuple(present[start:stop])


def _full_alpha_partitions():
    partitions = alpha_partitions()
    selected = tuple(sorted(alpha_id for _name, ids in partitions for alpha_id in ids))
    if not selection_is_focused() and selected != formula_ids():
        raise AssertionError("unfiltered stream scenario must cover all 101 formulas")
    return partitions


def test_trace_validator_rejects_unknown_panel_contract_before_inspection():
    with pytest.raises(ValueError, match="panel_contract"):
        validate_factor_trace(
            None,
            0,
            {},
            (),
            (),
            strategy=None,
            panel_contract="guess",
        )


def _gap_reference_frames(
    frames: Mapping[str, pd.DataFrame], gap_target: str, gap_point: datetime
) -> Dict[str, pd.DataFrame]:
    projected = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    source_index = projected[gap_target].index
    matching = [point for point in source_index if _as_utc(point) == gap_point]
    if len(matching) != 1:
        raise AssertionError("gap time is not represented exactly once by its target fixture")
    projected[gap_target] = projected[gap_target].drop(index=matching[0])
    return projected


def _assert_pre_gap_and_recovery_witnesses(
    alpha_id: int,
    expected: Sequence[Sequence[float]],
    *,
    span: int,
    gap_index: int,
    recovery_index: int,
) -> None:
    before = [
        float(value)
        for row in expected[max(WARMUP_BARS, span + 1) : gap_index]
        for value in row
        if math.isfinite(float(value))
    ]
    after = [
        float(value)
        for row in expected[recovery_index:]
        for value in row
        if math.isfinite(float(value))
    ]
    if len({value.hex() for value in before}) < 2:
        raise AssertionError(
            "Alpha%d lacks a finite varying witness before its explicit gap" % alpha_id
        )
    if len({value.hex() for value in after}) < 2:
        raise AssertionError(
            "Alpha%d lacks a finite varying witness after full-window recovery" % alpha_id
        )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_full_alpha101_gap_advances_one_planned_grid_and_blocks_then_recovers(factor_mode):
    """One explicit gap blocks decisions until a full clean factor/cohort span returns."""

    frames = positive_target_frames(_GAP_ROWS)
    targets = tuple(frames)
    gap_target = targets[-1]
    gap_index = _GAP_INDEX
    partitions = _full_alpha_partitions()
    checked = set()

    for _batch_name, alpha_ids in partitions:
        strategy, cohort, clock, grid = _run_live(
            frames,
            alpha_ids,
            factor_mode=factor_mode,
            gap_target=gap_target,
            gap_index=gap_index,
            run_label="gap",
        )
        _assert_contiguous_complete_grid(strategy, cohort, grid)
        if not clock.waits:
            raise AssertionError("gap stream did not wait for source availability")
        for index, record in enumerate(strategy.readings):
            for name, receipt in record["receipts"].items():
                expected_present = not (name == gap_target and index == gap_index)
                if receipt.present is not expected_present:
                    raise AssertionError("live presence mask differs from the one explicit gap")

        # A separate ordinary Cerebro run provides the no-gap control. The
        # independent scalar oracle below validates both runs before their
        # exact H+warmup recovery slots are compared.
        control, control_cohort, _control_clock, control_grid = _run_live(
            frames,
            alpha_ids,
            factor_mode=factor_mode,
            run_label="gap-no-gap-control",
        )
        _assert_contiguous_complete_grid(control, control_cohort, control_grid)
        if tuple(control_grid) != tuple(grid):
            raise AssertionError("no-gap control changed the planned source grid")

        oracle_frames = _gap_reference_frames(frames, gap_target, grid[gap_index])
        _traces, reports = _trace_for(
            strategy,
            oracle_frames,
            alpha_ids,
            grid,
            panel_contract="live_snapshot",
        )
        _control_traces, control_reports = _trace_for(
            control,
            frames,
            alpha_ids,
            control_grid,
            panel_contract="live_snapshot",
        )
        required_bars = max(
            [WARMUP_BARS]
            + [
                int(
                    strategy.live_factor_set.factor_instances["alpha%d" % alpha_id][
                        "default"
                    ]._minperiod
                )
                for alpha_id in alpha_ids
            ]
        )
        for alpha_id in alpha_ids:
            instance = strategy.live_factor_set.factor_instances["alpha%d" % alpha_id]["default"]
            # Structural span is independent of the intentionally dropped row;
            # the original frames keep equal lengths for history_h's source scan.
            span = history_h(alpha_id, frames)
            if int(instance._minperiod) != span + 1:
                raise AssertionError(
                    "Alpha%d runtime dependency count %r disagrees with independent span %d"
                    % (alpha_id, instance._minperiod, span + 1)
                )

            gap_output = strategy.readings[gap_index]["outputs"]["alpha%d" % alpha_id][gap_target]
            if (
                gap_output.present is not False
                or gap_output.quality != "MISSING"
                or getattr(gap_output.status, "value", gap_output.status) != "OUTPUT_UNAVAILABLE"
                or not math.isnan(float(gap_output.value))
            ):
                raise AssertionError(
                    "Alpha%d gap did not remain explicit and unavailable" % alpha_id
                )
            expected = reports[alpha_id]["expected"]
            if not math.isnan(float(expected[gap_index][targets.index(gap_target)])):
                raise AssertionError(
                    "Alpha%d independent oracle did not mask the missing member" % alpha_id
                )
            clean_bars = max(span + 1, WARMUP_BARS)
            factor_recovery = gap_index + clean_bars
            if factor_recovery >= len(grid):
                raise AssertionError(
                    "Alpha%d fixture ends before its full-window recovery" % alpha_id
                )
            control_expected = control_reports[alpha_id]["expected"]
            actual_expected = expected[factor_recovery]
            clean_expected = control_expected[factor_recovery]
            if len(actual_expected) != len(targets) or len(clean_expected) != len(targets):
                raise AssertionError("Alpha%d recovery oracle omitted a target" % alpha_id)
            for target_index, target in enumerate(targets):
                if not _same_number(
                    float(actual_expected[target_index]), float(clean_expected[target_index])
                ):
                    raise AssertionError(
                        "Alpha%d independent gap/control oracle differs at its clean cutoff for %s"
                        % (alpha_id, target)
                    )
                gap_output = strategy.readings[factor_recovery]["outputs"][
                    "alpha%d" % alpha_id
                ][target]
                control_output = control.readings[factor_recovery]["outputs"][
                    "alpha%d" % alpha_id
                ][target]
                _assert_snapshot_output_equal(
                    gap_output,
                    control_output,
                    label="Alpha%d clean-cutoff target %s" % (alpha_id, target),
                )
                if not _same_number(float(gap_output.value), float(actual_expected[target_index])):
                    raise AssertionError(
                        "Alpha%d clean-cutoff live value differs from its independent oracle for %s"
                        % (alpha_id, target)
                    )
                if gap_output.present is not True or gap_output.complete is not True:
                    raise AssertionError(
                        "Alpha%d clean cutoff did not carry complete present input for %s"
                        % (alpha_id, target)
                    )
            _assert_pre_gap_and_recovery_witnesses(
                alpha_id,
                expected,
                span=span,
                gap_index=gap_index,
                recovery_index=factor_recovery,
            )
            assert_evaluation_witness(
                alpha_id,
                expected,
                evaluation_bars=len(grid) - factor_recovery,
                warmup_start=factor_recovery,
            )
            if factor_recovery < gap_index + required_bars:
                cutoff_record = strategy.readings[factor_recovery]
                if (
                    getattr(cutoff_record["readiness"], "value", cutoff_record["readiness"])
                    != "WARMUP"
                    or cutoff_record["batch_id"] in strategy.eligible_batches
                ):
                    raise AssertionError(
                        "Alpha%d factor H recovery was conflated with group decision readiness"
                        % alpha_id
                    )
            else:
                cutoff_record = strategy.readings[factor_recovery]
                if (
                    getattr(cutoff_record["readiness"], "value", cutoff_record["readiness"])
                    != "LIVE_READY"
                    or cutoff_record["batch_id"] not in strategy.eligible_batches
                ):
                    raise AssertionError(
                        "Alpha%d clean cutoff did not preserve already-qualified group readiness"
                        % alpha_id
                    )
            checked.add(alpha_id)

        recovery_index = gap_index + required_bars
        if recovery_index >= len(grid):
            raise AssertionError("scenario grid ends before the whole registered group recovers")
        for index in range(gap_index, recovery_index):
            record = strategy.readings[index]
            readiness = getattr(record["readiness"], "value", record["readiness"])
            if readiness == "LIVE_READY" or record["batch_id"] in strategy.eligible_batches:
                raise AssertionError("group produced a new decision-eligible batch before recovery")
        if "cohort_gap_present" not in strategy.readings[gap_index]["readiness_reasons"]:
            raise AssertionError("the exact missing slot is absent from readiness diagnostics")
        if getattr(strategy.readings[recovery_index]["readiness"], "value", None) != "LIVE_READY":
            raise AssertionError("whole group did not become ready at its complete recovery window")
        if strategy.readings[recovery_index]["batch_id"] not in strategy.eligible_batches:
            raise AssertionError("whole group did not resume eligibility after complete recovery")
        if (
            getattr(control.readings[recovery_index]["readiness"], "value", None) != "LIVE_READY"
            or control.readings[recovery_index]["batch_id"] not in control.eligible_batches
        ):
            raise AssertionError("no-gap group control did not meet readiness at the gap cutoff")
        for record in (strategy.readings[recovery_index], control.readings[recovery_index]):
            for name, receipt in record["receipts"].items():
                if (
                    receipt.present is not True
                    or receipt.complete is not True
                    or receipt.quality != "GOOD"
                ):
                    raise AssertionError(
                        "group recovery contains incomplete or missing source input: %s" % name
                    )

    if not selection_is_focused() and checked != set(formula_ids()):
        raise AssertionError("gap scenario omitted a registered Alpha101 formula")


@pytest.mark.integration
@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_alpha007_gap_snapshot_keeps_raw_false_branch_separate_from_group_readiness(
    factor_mode,
):
    """A valid false branch stays observable while the missing-input window warms up."""

    frames = positive_target_frames(_GAP_ROWS)
    targets = tuple(frames)
    gap_target = targets[-1]
    strategy, _cohort, _clock, grid = _run_live(
        frames,
        (7,),
        factor_mode=factor_mode,
        gap_target=gap_target,
        gap_index=_GAP_INDEX,
        run_label="alpha007-gap-output-readiness",
    )
    reference = _gap_reference_frames(frames, gap_target, grid[_GAP_INDEX])
    _traces, reports = _trace_for(
        strategy,
        reference,
        (7,),
        grid,
        panel_contract="live_snapshot",
    )
    asset_index = targets.index(gap_target)
    gap_output = strategy.readings[_GAP_INDEX]["outputs"]["alpha7"][gap_target]
    assert gap_output.present is False
    assert gap_output.quality == "MISSING"
    assert gap_output.status.value == "OUTPUT_UNAVAILABLE"
    assert math.isnan(float(gap_output.value))
    assert gap_output.reason == "UNKNOWN"
    assert getattr(strategy.readings[_GAP_INDEX]["readiness"], "value", None) == "WARMUP"

    # Twenty rows after the gap, the graph's active rolling branch is
    # still incomplete, but Alpha007's valid false branch is the exact -1.
    # The snapshot exposes that raw result while cohort readiness blocks decisions.
    branch_index = _GAP_INDEX + 20
    branch_record = strategy.readings[branch_index]
    branch_output = branch_record["outputs"]["alpha7"][gap_target]
    assert branch_record["receipts"][gap_target].present is True
    assert branch_output.status.value == "OUTPUT_AVAILABLE"
    assert branch_output.reason is None
    assert float(branch_output.value) == -1.0
    assert reports[7]["expected"][branch_index][asset_index] == -1.0
    assert reports[7]["actual"][branch_index][asset_index] == -1.0
    assert reports[7]["panel_contract"] == "live_snapshot"
    assert reports[7]["panel_expected"][branch_index][asset_index] == -1.0
    assert reports[7]["panel_actual"][branch_index][asset_index] == -1.0
    assert getattr(branch_record["readiness"], "value", None) == "WARMUP"
    assert branch_record["batch_id"] not in strategy.eligible_batches

    recovery_index = _GAP_INDEX + history_h(7, frames) + 1
    assert recovery_index < len(grid)
    recovered_record = strategy.readings[recovery_index]
    assert getattr(recovered_record["readiness"], "value", None) == "LIVE_READY"
    assert recovered_record["batch_id"] in strategy.eligible_batches


def _perturb_future_frames(
    frames: Mapping[str, pd.DataFrame], start_index: int
) -> Dict[str, pd.DataFrame]:
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for asset_index, (asset, frame) in enumerate(changed.items()):
        for row_index in range(start_index, len(frame)):
            old = frames[asset].iloc[row_index]
            open_value = float(old.open) * (1.03 + 0.002 * asset_index) + 0.11 * asset_index
            close_value = float(old.close) * (0.97 - 0.001 * asset_index) - 0.07 * asset_index
            frame.iat[row_index, frame.columns.get_loc("open")] = open_value
            frame.iat[row_index, frame.columns.get_loc("close")] = close_value
            frame.iat[row_index, frame.columns.get_loc("high")] = max(open_value, close_value) + 1.7
            frame.iat[row_index, frame.columns.get_loc("low")] = min(open_value, close_value) - 1.3
            frame.iat[row_index, frame.columns.get_loc("volume")] = (
                float(old.volume) * (1.2 + asset_index * 0.01) + row_index * 13.0
            )
            frame.iat[row_index, frame.columns.get_loc("openinterest")] = (
                float(old.openinterest) + 101.0 + asset_index * 17.0
            )
            frame.iat[row_index, frame.columns.get_loc("vwap")] = (
                float(old.vwap) * 1.11 + asset_index * 0.23
            )
            frame.iat[row_index, frame.columns.get_loc("dollar_volume")] = (
                float(old.dollar_volume) * (1.6 + asset_index * 0.02) + row_index * 29.0
            )
            frame.iat[row_index, frame.columns.get_loc("cap")] = (
                float(old.cap) * 1.4 + asset_index * 5_000.0
            )
            for category_index, field in enumerate(("sector", "industry", "subindustry"), 1):
                frame.iat[row_index, frame.columns.get_loc(field)] = float(
                    old[field]
                ) + category_index * (asset_index + 1)
    return changed


def _assert_alpha_witness_inside_prefix(
    alpha_id: int, expected: Sequence[Sequence[float]], prefix_rows: int
) -> None:
    span = history_h(alpha_id)
    warmup_start = max(WARMUP_BARS, span + 1)
    evaluation_bars = prefix_rows - warmup_start
    if evaluation_bars <= 0:
        raise AssertionError("causal prefix ends before its structural finite history")
    assert_evaluation_witness(
        alpha_id,
        expected[:prefix_rows],
        evaluation_bars=evaluation_bars,
        warmup_start=warmup_start,
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_full_alpha101_future_fields_benchmark_and_member_order_keep_sealed_prefix(factor_mode):
    """Future prices, derived/PIT fields, arrival time, and feed order cannot alter prior rows."""

    base_frames = positive_target_frames(_CAUSAL_ROWS)
    targets = tuple(base_frames)
    benchmark_and_targets = targets + (BENCHMARK_NAME,)
    changed_frames = _perturb_future_frames(base_frames, _CAUSAL_PREFIX_ROWS)
    for asset in targets:
        left = base_frames[asset].iloc[_CAUSAL_PREFIX_ROWS:]
        right = changed_frames[asset].iloc[_CAUSAL_PREFIX_ROWS:]
        changed_fields = {
            field
            for field in TARGET_LINE_FIELDS
            if any(
                not _same_cell(left.iloc[row][field], right.iloc[row][field])
                for row in range(len(left))
            )
        }
        if changed_fields != set(TARGET_LINE_FIELDS):
            raise AssertionError(
                "future perturbation did not change every declared target field: %r"
                % sorted(set(TARGET_LINE_FIELDS) - changed_fields)
            )

    partitions = _full_alpha_partitions()
    checked = set()
    for _batch_name, alpha_ids in partitions:
        baseline, baseline_cohort, _base_clock, grid = _run_live(
            base_frames,
            alpha_ids,
            factor_mode=factor_mode,
            availability_delay_seconds=2,
            run_label="causal-base",
        )
        changed, changed_cohort, _changed_clock, changed_grid = _run_live(
            changed_frames,
            alpha_ids,
            factor_mode=factor_mode,
            future_available_from=_CAUSAL_PREFIX_ROWS,
            availability_delay_seconds=AVAILABILITY_DELAY_SECONDS,
            feed_order=tuple(reversed(benchmark_and_targets)),
            run_label="causal-future-permuted",
        )
        _assert_contiguous_complete_grid(baseline, baseline_cohort, grid)
        _assert_contiguous_complete_grid(changed, changed_cohort, changed_grid)
        if tuple(grid) != tuple(changed_grid):
            raise AssertionError("future perturbation changed the fixed sealed grid")
        if not _base_receipt_prefix_equal(
            baseline,
            changed,
            prefix_rows=_CAUSAL_PREFIX_ROWS,
            targets=targets,
        ):
            raise AssertionError("future arrival or member order changed a prior sealed receipt")
        benchmark_prefix_after = changed.readings[_CAUSAL_PREFIX_ROWS - 1]["receipts"][
            BENCHMARK_NAME
        ].envelope.raw_values
        benchmark_future_before = baseline.readings[_CAUSAL_PREFIX_ROWS]["receipts"][
            BENCHMARK_NAME
        ].envelope.raw_values
        benchmark_future_after = changed.readings[_CAUSAL_PREFIX_ROWS]["receipts"][
            BENCHMARK_NAME
        ].envelope.raw_values
        if any(
            not _same_cell(
                baseline.readings[_CAUSAL_PREFIX_ROWS - 1]["receipts"][
                    BENCHMARK_NAME
                ].envelope.raw_values[field],
                benchmark_prefix_after[field],
            )
            for field in BASE_LINE_FIELDS
        ):
            raise AssertionError("benchmark perturbation changed a sealed-prefix source field")
        changed_benchmark_fields = {
            field
            for field in BASE_LINE_FIELDS
            if not _same_cell(benchmark_future_before[field], benchmark_future_after[field])
        }
        if changed_benchmark_fields != set(BASE_LINE_FIELDS):
            raise AssertionError(
                "future benchmark perturbation missed fields: %r"
                % sorted(set(BASE_LINE_FIELDS) - changed_benchmark_fields)
            )
        if (
            baseline.readings[_CAUSAL_PREFIX_ROWS - 1]["available_at"]
            != changed.readings[_CAUSAL_PREFIX_ROWS - 1]["available_at"]
        ):
            raise AssertionError("future availability change rewrote the prefix batch time")
        if (
            baseline.readings[_CAUSAL_PREFIX_ROWS]["receipts"][BENCHMARK_NAME].available_at
            == changed.readings[_CAUSAL_PREFIX_ROWS]["receipts"][BENCHMARK_NAME].available_at
        ):
            raise AssertionError("future source arrival perturbation was not observed")

        baseline_traces, baseline_reports = _trace_for(
            baseline, base_frames, alpha_ids, grid, panel_contract="live_snapshot"
        )
        changed_traces, changed_reports = _trace_for(
            changed, changed_frames, alpha_ids, grid, panel_contract="live_snapshot"
        )
        _materialize_presence_segment(baseline, 0, _CAUSAL_PREFIX_ROWS)
        _materialize_presence_segment(changed, 0, _CAUSAL_PREFIX_ROWS)
        for alpha_id in alpha_ids:
            _assert_alpha_witness_inside_prefix(
                alpha_id, baseline_reports[alpha_id]["expected"], _CAUSAL_PREFIX_ROWS
            )
            _assert_alpha_witness_inside_prefix(
                alpha_id, changed_reports[alpha_id]["expected"], _CAUSAL_PREFIX_ROWS
            )
            segment = _graph_segment_equal(
                baseline_traces[alpha_id],
                changed_traces[alpha_id],
                alpha_id,
                left_slice=slice(0, _CAUSAL_PREFIX_ROWS),
                right_slice=slice(0, _CAUSAL_PREFIX_ROWS),
            )
            if segment["node_reason_cells"] <= 0:
                raise AssertionError("causal prefix comparison omitted logical reason lines")
            checked.add(alpha_id)

    if not selection_is_focused() and checked != set(formula_ids()):
        raise AssertionError("future-causality scenario omitted a registered Alpha101 formula")


def _base_receipt_prefix_equal(
    left: _ScenarioCapture,
    right: _ScenarioCapture,
    *,
    prefix_rows: int,
    targets: Sequence[str],
) -> bool:
    if len(left.readings) < prefix_rows or len(right.readings) < prefix_rows:
        return False
    for index in range(prefix_rows):
        left_record, right_record = left.readings[index], right.readings[index]
        if left_record["close_time"] != right_record["close_time"]:
            return False
        if left_record["available_at"] != right_record["available_at"]:
            return False
        if left_record["callback_time"] != right_record["callback_time"]:
            return False
        for name in tuple(targets) + (BENCHMARK_NAME,):
            left_receipt = left_record["receipts"][name]
            right_receipt = right_record["receipts"][name]
            if (
                left_receipt.bar_id != right_receipt.bar_id
                or left_receipt.member_id != right_receipt.member_id
                or left_receipt.source_role != right_receipt.source_role
                or left_receipt.present is not right_receipt.present
                or left_receipt.complete is not right_receipt.complete
                or left_receipt.quality != right_receipt.quality
                or left_receipt.missing_fields != right_receipt.missing_fields
                or left_receipt.available_at != right_receipt.available_at
                or dict(left_receipt.envelope.raw_values) != dict(right_receipt.envelope.raw_values)
            ):
                return False
            for field in (
                "calendar_id",
                "epoch_id",
                "slot_index",
                "slot_id",
                "instrument",
                "source_ref",
                "connection_generation",
                "feed_sequence",
                "bucket_start",
                "close_time",
                "available_at",
                "trading_day",
                "session_segment",
                "timezone_id",
                "clock_domain_id",
                "complete",
                "quality",
                "quality_flags",
                "event_source",
            ):
                if getattr(left_receipt.envelope, field) != getattr(right_receipt.envelope, field):
                    return False
    return True


def _span_proof(strategy: _ScenarioCapture, alpha_ids: Sequence[int], frames) -> Dict[int, int]:
    """Bind each independent AST span to the executed operator graph's minperiod."""

    required = {}
    for alpha_id in alpha_ids:
        factor_name = "alpha%d" % alpha_id
        spec = strategy.p.plan.factors[factor_name]
        instance = strategy.live_factor_set.factor_instances[factor_name]["default"]
        independent_span = history_h(alpha_id, frames)
        if spec.lookback_h != independent_span:
            raise AssertionError(
                "Alpha%d FactorSpec H=%d differs from independent AST span=%d"
                % (alpha_id, spec.lookback_h, independent_span)
            )

        runtime_periods = [int(instance._minperiod)]
        nodes = tuple(getattr(instance, "_nodes", {}).values())
        if not nodes:
            raise AssertionError(
                "Alpha%d runtime graph contains no proven operator nodes" % alpha_id
            )
        for node in nodes:
            minimum = getattr(node, "_minperiod", None)
            if minimum is None or int(minimum) < 1:
                raise AssertionError(
                    "Alpha%d graph node has no finite runtime minperiod" % alpha_id
                )
            runtime_periods.append(int(minimum))
            period = getattr(getattr(node, "p", None), "period", None)
            if period is not None and (
                isinstance(period, bool)
                or not isinstance(period, (int, float))
                or not math.isfinite(float(period))
                or float(period) < 0.0
            ):
                raise AssertionError("Alpha%d graph has an unbounded temporal operator" % alpha_id)
        for lines in instance._field_line_cache.values():
            for line in lines:
                owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
                minimum = getattr(owner, "_minperiod", 1) if owner is not None else 1
                if isinstance(minimum, bool) or int(minimum) < 1:
                    raise AssertionError(
                        "Alpha%d bound field has no finite runtime history" % alpha_id
                    )
                runtime_periods.append(int(minimum))

        actual_required_bars = max(runtime_periods)
        if actual_required_bars != independent_span + 1:
            raise AssertionError(
                "Alpha%d executed graph needs %d bars; independent AST proves %d"
                % (alpha_id, actual_required_bars, independent_span + 1)
            )
        required[alpha_id] = actual_required_bars
    return required


def _compare_graph_tail(
    continuous: _ScenarioCapture,
    rebuilt: _ScenarioCapture,
    alpha_ids: Sequence[int],
    *,
    continuous_grid: Sequence[datetime],
    rebuilt_grid: Sequence[datetime],
    suffix_rows: int,
) -> None:
    left_slice = slice(len(continuous_grid) - suffix_rows, len(continuous_grid))
    right_slice = slice(len(rebuilt_grid) - suffix_rows, len(rebuilt_grid))
    if tuple(continuous_grid[left_slice]) != tuple(rebuilt_grid[right_slice]):
        raise AssertionError("finite rebuild and continuous run have different suffix timestamps")
    for alpha_id in alpha_ids:
        left_factor = FullGridFactorTraceView(
            continuous.live_factor_set.factor_instances["alpha%d" % alpha_id]["default"],
            continuous_grid,
        )
        right_factor = FullGridFactorTraceView(
            rebuilt.live_factor_set.factor_instances["alpha%d" % alpha_id]["default"],
            rebuilt_grid,
        )
        _graph_segment_equal(
            left_factor,
            right_factor,
            alpha_id,
            left_slice=left_slice,
            right_slice=right_slice,
        )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_full_alpha101_finite_qualified_history_rebuild_matches_cold_live_suffix(factor_mode):
    """Finite prewarm length comes from independent AST plus executed graph span proof."""

    full_frames = positive_target_frames(_REBUILD_ROWS)
    targets = tuple(full_frames)
    checked = set()
    suffix_rows = _REBUILD_SUFFIX_ROWS

    for _batch_name, alpha_ids in _full_alpha_partitions():
        continuous, continuous_cohort, _clock, continuous_grid = _run_live(
            full_frames,
            alpha_ids,
            factor_mode=factor_mode,
            run_label="rebuild-continuous",
        )
        _assert_contiguous_complete_grid(continuous, continuous_cohort, continuous_grid)
        _continuous_traces, continuous_reports = _trace_for(
            continuous,
            full_frames,
            alpha_ids,
            continuous_grid,
            panel_contract="live_snapshot",
        )
        required_by_id = _span_proof(continuous, alpha_ids, full_frames)
        history_count = max(WARMUP_BARS, max(required_by_id.values()))
        if history_count >= len(full_frames[targets[0]]):
            raise AssertionError("finite qualified history leaves no common live suffix")

        finite_rows = history_count + suffix_rows
        cut = len(full_frames[targets[0]]) - finite_rows
        finite_frames = {
            asset: frame.iloc[cut:].copy(deep=True) for asset, frame in full_frames.items()
        }
        rebuilt, rebuilt_cohort, _rebuilt_clock, rebuilt_grid = _run_live(
            finite_frames,
            alpha_ids,
            factor_mode=factor_mode,
            history_count=history_count,
            run_label="rebuild-history-live",
        )
        _assert_contiguous_complete_grid(rebuilt, rebuilt_cohort, rebuilt_grid)
        _rebuilt_traces, rebuilt_reports = _trace_for(
            rebuilt,
            finite_frames,
            alpha_ids,
            rebuilt_grid,
            panel_contract="live_snapshot",
        )
        if history_count >= len(rebuilt.readings):
            raise AssertionError("finite prewarm has no first live source batch")
        for record in rebuilt.readings[:history_count]:
            if any(receipt.source_role != "history" for receipt in record["receipts"].values()):
                raise AssertionError("qualified prewarm prefix contains a non-history receipt")
        first_live = rebuilt.readings[history_count]
        for name, feed in rebuilt.feed_by_name.items():
            receipt = first_live["receipts"][name]
            member = rebuilt_cohort.member_for_feed(feed)
            cutover = first_live["cutovers"].get(member.member_id)
            if (
                receipt.source_role != "live"
                or cutover is None
                or cutover.crossed_live is not True
                or cutover.transition_kind != "history_to_live"
                or cutover.first_live_receipt is not receipt
            ):
                raise AssertionError("finite prewarm lacks an exact history-to-live cutover")
        continuous_suffix_start = len(continuous_grid) - suffix_rows
        rebuilt_suffix_start = len(rebuilt_grid) - suffix_rows
        _materialize_presence_segment(continuous, continuous_suffix_start, len(continuous_grid))
        _materialize_presence_segment(rebuilt, rebuilt_suffix_start, len(rebuilt_grid))
        for alpha_id in alpha_ids:
            required = required_by_id[alpha_id]
            if required > history_count:
                raise AssertionError(
                    "finite prewarm history is shorter than an executed factor span"
                )
            if rebuilt.readings[history_count]["batch_id"] not in rebuilt.eligible_batches:
                raise AssertionError(
                    "rebuilt graph did not become live-ready on its first fresh slot"
                )
            suffix_start = len(rebuilt_grid) - suffix_rows
            for index in range(suffix_start, len(rebuilt_grid)):
                for name, receipt in rebuilt.readings[index]["receipts"].items():
                    if receipt.source_role != "live":
                        raise AssertionError("rebuilt comparison suffix is not live-sourced")
                if getattr(rebuilt.readings[index]["readiness"], "value", None) != "LIVE_READY":
                    raise AssertionError("rebuilt suffix is not eligible after qualified prewarm")
            assert_evaluation_witness(
                alpha_id,
                rebuilt_reports[alpha_id]["expected"],
                evaluation_bars=suffix_rows,
                warmup_start=history_count,
            )
            assert_evaluation_witness(
                alpha_id,
                continuous_reports[alpha_id]["expected"],
                evaluation_bars=suffix_rows,
                warmup_start=max(WARMUP_BARS, required_by_id[alpha_id]),
            )
            checked.add(alpha_id)

        _compare_graph_tail(
            continuous,
            rebuilt,
            alpha_ids,
            continuous_grid=continuous_grid,
            rebuilt_grid=rebuilt_grid,
            suffix_rows=suffix_rows,
        )

    if not selection_is_focused() and checked != set(formula_ids()):
        raise AssertionError("finite-history rebuild omitted a registered Alpha101 formula")


def _recursive_factor_spec(
    indicator: type = _RecursiveClose,
) -> Mapping[str, FactorSpec]:
    return {
        "recursive_close": FactorSpec(
            name="recursive_close",
            indicator=indicator,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
            mode="native",
        )
    }


def _positive_target_prefix(periods: int) -> Dict[str, pd.DataFrame]:
    """Use the accepted 320-row fixture, then keep a bounded scenario prefix."""
    if type(periods) is not int or not 1 <= periods <= 320:
        raise ValueError("periods must be in 1..320")
    return {
        target: frame.iloc[:periods].copy(deep=True)
        for target, frame in positive_target_frames(320).items()
    }


def _recursive_values(
    strategy: _ScenarioCapture, targets: Sequence[str]
) -> Dict[str, Tuple[float, ...]]:
    return {
        target: tuple(
            float(record["outputs"]["recursive_close"][target].value)
            for record in strategy.readings
        )
        for target in targets
    }


def _recursive_close_oracle(frames: Mapping[str, pd.DataFrame]) -> Dict[str, Tuple[float, ...]]:
    """Evaluate the custom recurrence directly from each source close series."""

    expected = {}
    for target, frame in frames.items():
        state = 0.0
        values = []
        for raw_close in frame["close"]:
            state = 0.5 * state + float(raw_close)
            values.append(state)
        expected[target] = tuple(values)
    return expected


@pytest.mark.integration
def test_recursive_custom_factor_history_to_live_oracle_rejects_truncated_h0_equivalence():
    """A supplied complete prefix preserves recurrence; an H=0 tail differs."""

    frames = positive_target_frames(320)
    targets = tuple(frames)
    spec = _recursive_factor_spec()
    history_count = 290
    rebuilt_from_genesis, cohort, _clock, rebuilt_grid = _run_live(
        frames,
        factor_specs=spec,
        history_count=history_count,
        source_origins=_source_origins(frames, source_role="history"),
        run_label="recursive-history-to-live-genesis",
    )

    if tuple(rebuilt_grid) != tuple(frames[targets[0]].index):
        raise AssertionError("recursive genesis replay changed the full source grid")
    if len(rebuilt_from_genesis.readings) != len(rebuilt_grid):
        raise AssertionError("recursive history-to-live replay omitted planned slots")
    for index, record in enumerate(rebuilt_from_genesis.readings[:history_count]):
        if record["close_time"] != rebuilt_grid[index]:
            raise AssertionError("recursive history prefix did not begin at source genesis")
        if any(receipt.source_role != "history" for receipt in record["receipts"].values()):
            raise AssertionError("recursive genesis prefix contains a non-history receipt")
        for target in targets:
            receipt = record["receipts"][target]
            if float(receipt.envelope.raw_values["close"]) != float(
                frames[target]["close"].iloc[index]
            ):
                raise AssertionError("recursive history receipt differs from the genesis source")

    first_live = rebuilt_from_genesis.readings[history_count]
    for name, feed in rebuilt_from_genesis.feed_by_name.items():
        receipt = first_live["receipts"][name]
        member = cohort.member_for_feed(feed)
        cutover = first_live["cutovers"].get(member.member_id)
        if (
            receipt.source_role != "live"
            or cutover is None
            or cutover.crossed_live is not True
            or cutover.transition_kind != "history_to_live"
            or cutover.first_live_receipt is not receipt
        ):
            raise AssertionError("recursive replay lacks its exact history-to-live cutover")
    if getattr(first_live["readiness"], "value", first_live["readiness"]) != "LIVE_READY":
        raise AssertionError("recursive full-genesis history did not qualify the first live slot")

    genesis_values = _recursive_values(rebuilt_from_genesis, targets)
    expected_values = _recursive_close_oracle(frames)
    for target in targets:
        for index in range(history_count, len(rebuilt_grid)):
            if genesis_values[target][index] != expected_values[target][index]:
                raise AssertionError(
                    "recursive history-to-live value differs from the genesis oracle: %s[%d]"
                    % (target, index)
                )
        if genesis_values[target][-20:] != expected_values[target][-20:]:
            raise AssertionError("recursive common live suffix differs from the genesis oracle")

    # The API accepts finite history based on its declared H/warmup contract;
    # it has no source-genesis identity with which to reject this truncated
    # history. Exercise that route and prove its H=0 result is not equivalent.
    truncated_history_count = WARMUP_BARS
    suffix_rows = 20
    cut = len(rebuilt_grid) - truncated_history_count - suffix_rows
    truncated_frames = {
        target: frame.iloc[cut:].copy(deep=True) for target, frame in frames.items()
    }
    truncated, truncated_cohort, _clock, truncated_grid = _run_live(
        truncated_frames,
        factor_specs=spec,
        history_count=truncated_history_count,
        source_origins=_source_origins(frames, source_role="history"),
        run_label="recursive-history-truncated-h0-control",
    )
    if tuple(truncated_grid[-suffix_rows:]) != tuple(rebuilt_grid[-suffix_rows:]):
        raise AssertionError("recursive truncated history lacks the common live suffix")
    truncated_first_live = truncated.readings[truncated_history_count]
    if (
        getattr(truncated_first_live["readiness"], "value", truncated_first_live["readiness"])
        != "WARMUP"
    ):
        raise AssertionError("truncated H=0 history incorrectly qualified for LIVE_READY")
    if "history_origin_unverified" not in truncated_first_live["readiness_reasons"]:
        raise AssertionError("truncated H=0 history lost its source-origin failure reason")
    if any(
        output.status.value != "OUTPUT_AVAILABLE"
        for output in truncated_first_live["outputs"]["recursive_close"].values()
    ):
        raise AssertionError("unqualified reconstruction hid diagnostic factor outputs")
    for name, feed in truncated.feed_by_name.items():
        receipt = truncated_first_live["receipts"][name]
        member = truncated_cohort.member_for_feed(feed)
        cutover = truncated_first_live["cutovers"].get(member.member_id)
        if (
            receipt.source_role != "live"
            or cutover is None
            or cutover.transition_kind != "history_to_live"
            or cutover.first_live_receipt is not receipt
        ):
            raise AssertionError("truncated control did not reach history-to-live cutover")

    truncated_values = _recursive_values(truncated, targets)
    if not any(
        truncated_values[target][-suffix_rows:] != expected_values[target][-suffix_rows:]
        for target in targets
    ):
        raise AssertionError("truncated H=0 history was incorrectly equivalent to genesis")


@pytest.mark.integration
def test_recursive_replay_origin_and_unknown_contract_gate_actual_readiness():
    # Only an exact live source origin qualifies recursion; outputs stay diagnostic.
    frames = _positive_target_prefix(61)
    targets = tuple(frames)

    unknown, _cohort, _clock, _grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(_UnqualifiedRecursiveClose),
        run_label="recursive-unknown-contract",
    )
    unknown_snapshot = unknown.readings[-1]
    if getattr(unknown_snapshot["readiness"], "value", None) != "WARMUP":
        raise AssertionError("custom recursive factor without a contract reached LIVE_READY")
    if "history_reconstruction_unqualified" not in unknown_snapshot["readiness_reasons"]:
        raise AssertionError("unknown reconstruction contract lost its explicit reason")
    if any(
        output.status.value != "OUTPUT_AVAILABLE"
        for output in unknown_snapshot["outputs"]["recursive_close"].values()
    ):
        raise AssertionError("unknown reconstruction contract hid computed outputs")

    missing_origin, _cohort, _clock, _grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(),
        run_label="recursive-origin-missing",
    )
    missing_snapshot = missing_origin.readings[-1]
    if getattr(missing_snapshot["readiness"], "value", None) != "WARMUP":
        raise AssertionError("recursive replay without an origin reached LIVE_READY")
    if "history_origin_unverified" not in missing_snapshot["readiness_reasons"]:
        raise AssertionError("missing origin lost its precise reconstruction reason")

    replayed, _cohort, _clock, _grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(),
        source_origins=_source_origins(frames, source_role="live"),
        allow_history_prewarm=False,
        run_label="recursive-live-cold-start-origin",
    )
    snapshot = replayed.readings[-1]
    if getattr(snapshot["readiness"], "value", None) != "LIVE_READY":
        raise AssertionError("exact live cold-start origin did not qualify recursive replay")
    expected = _recursive_close_oracle(frames)
    actual = _recursive_values(replayed, targets)
    for target in targets:
        if actual[target] != expected[target]:
            raise AssertionError("live-origin recursion differs from its full-series oracle")

    history_count = 30
    history_replay, history_cohort, _clock, history_grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(),
        history_count=history_count,
        source_origins=_source_origins(frames, source_role="history"),
        max_window_bars=30,
        allow_history_prewarm=False,
        run_label="recursive-history-origin-prewarm-disabled",
    )
    if len(history_grid) - history_count <= 30:
        raise AssertionError("test must run beyond the retained live window")
    latest = history_replay.readings[-1]
    if getattr(latest["readiness"], "value", None) != "WARMUP":
        raise AssertionError("history-origin recursion forgot its prewarm dependency")
    if "history_prewarm_not_allowed" not in latest["readiness_reasons"]:
        raise AssertionError("history-origin recursion lost the disabled-prewarm reason")
    for target in targets:
        feed = history_replay.feed_by_name[target]
        window = history_cohort.complete_window_bars(feed, ("close",), 30)
        if len(window) != 30 or any(receipt.source_role != "live" for receipt in window):
            raise AssertionError("history rows were not evicted from the bounded live window")


@pytest.mark.integration
def test_finite_custom_history_contract_qualifies_and_checks_executed_graph_span():
    # A finite custom declaration works mid-series and cannot underclaim.
    source = _positive_target_prefix(100)
    frames = {target: frame.iloc[20:70].copy(deep=True) for target, frame in source.items()}
    strategy, _cohort, _clock, _grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(_FiniteWindowClose),
        history_count=30,
        run_label="finite-custom-mid-series-window",
    )
    first_live = strategy.readings[30]
    if getattr(first_live["readiness"], "value", None) != "LIVE_READY":
        raise AssertionError("declared finite custom window did not qualify after prewarm")
    for target, frame in frames.items():
        closes = tuple(float(value) for value in frame["close"])
        actual = tuple(
            float(record["outputs"]["recursive_close"][target].value)
            for record in strategy.readings
        )
        for index in range(2, len(closes)):
            expected = (closes[index] + closes[index - 1] + closes[index - 2]) / 3.0
            if actual[index] != expected:
                raise AssertionError("finite custom output differs from its three-row oracle")

    with pytest.raises(ResearchConfigError, match="finite_window history contract"):
        _run_live(
            frames,
            factor_specs=_recursive_factor_spec(_TooShortFiniteWindowClose),
            history_count=30,
            run_label="finite-custom-underdeclared-window",
        )


@pytest.mark.integration
def test_recursive_history_cutover_accepts_role_scoped_sequence_and_generation_reset():
    # History and live source counters are deliberately independent by role.
    frames = _positive_target_prefix(40)
    targets = tuple(frames)
    history_count = 30
    strategy, cohort, _clock, _grid = _run_live(
        frames,
        factor_specs=_recursive_factor_spec(),
        history_count=history_count,
        source_origins=_source_origins(frames, source_role="history"),
        reset_live_source_identity=True,
        run_label="recursive-role-scoped-source-counters",
    )

    first_live = strategy.readings[history_count]
    previous = strategy.readings[history_count - 1]
    for name, feed in strategy.feed_by_name.items():
        prior_receipt = previous["receipts"][name]
        receipt = first_live["receipts"][name]
        member = cohort.member_for_feed(feed)
        cutover = first_live["cutovers"].get(member.member_id)
        if (
            prior_receipt.source_role != "history"
            or receipt.source_role != "live"
            or receipt.feed_sequence >= prior_receipt.feed_sequence
            or receipt.envelope.connection_generation
            == prior_receipt.envelope.connection_generation
            or cutover is None
            or cutover.first_live_receipt is not receipt
        ):
            raise AssertionError("role-scoped provider identity was not independently reset")
    if getattr(first_live["readiness"], "value", None) != "LIVE_READY":
        raise AssertionError("exact genesis cutover failed on role-scoped counter reset")

    expected = _recursive_close_oracle(frames)
    actual = _recursive_values(strategy, targets)
    for target in targets:
        if actual[target][history_count:] != expected[target][history_count:]:
            raise AssertionError("role-scoped cutover changed full-history recurrence")
