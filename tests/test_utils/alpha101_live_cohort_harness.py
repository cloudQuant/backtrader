"""Real BtApiFeed/Cerebro harness for the full Alpha101 live-cohort matrix.

The fixture and formula expectations come from the accepted Alpha101 matrix
harness.  This module only adapts those deterministic fields to the ordinary
incremental Feed/Cohort path and exposes snapshot rows to the existing
independent node/reason validator.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import os
import random
from types import MappingProxyType, SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import pandas as pd

import backtrader as bt
from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.factor_indicator import FactorIndicator, _PresenceLine
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from tests.test_utils.alpha101_native_harness import (
    alpha_name,
    make_positive_fixture,
    selected_alpha_batches,
)


UTC = timezone.utc
BENCHMARK_NAME = "BENCHMARK"
TARGET_COUNT = 5
BATCH_SIZE = 20
DEFAULT_EVALUATION_LENGTHS = (320, 640, 1280)
EVALUATION_LENGTHS_ENV = "BT_LIVE_ALPHA101_LENGTHS"
WARMUP_BARS = 30
AVAILABILITY_DELAY_SECONDS = 2
MAX_PENDING_SLOTS = 2
WAIT_TIMEOUT_NS = 60_000_000_000
CLOCK_DOMAIN_ID = "iteration50-alpha101-cohort-clock-v1"
CALENDAR_ID = "iteration50-alpha101-common-daily-v1"
FREQUENCY = "1d"
FREQUENCY_SECONDS = 24 * 60 * 60

BASE_LINE_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
EXTRA_LINE_FIELDS = (
    "vwap",
    "cap",
    "sector",
    "industry",
    "subindustry",
    "dollar_volume",
)
TARGET_LINE_FIELDS = BASE_LINE_FIELDS + EXTRA_LINE_FIELDS


class ReplayClock:
    """Deterministic UTC/source clock for the normal Cerebro event loop."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self._monotonic_ns = 1_000
        self.waits = []

    def utc_now(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        return self._monotonic_ns

    def wait(self, timeout_seconds: float) -> None:
        timeout = max(0.0, float(timeout_seconds))
        self.waits.append(timeout)
        self._monotonic_ns += max(1, int(timeout * 1_000_000_000))
        self._now += timedelta(seconds=timeout)


def evaluation_lengths(environ: Optional[Mapping[str, str]] = None) -> Tuple[int, ...]:
    """Return selected canonical evaluation lengths; default to all three."""

    env = os.environ if environ is None else environ
    raw = env.get(EVALUATION_LENGTHS_ENV, "").strip()
    if not raw:
        return DEFAULT_EVALUATION_LENGTHS
    try:
        result = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(
            "%s must contain comma-separated evaluation lengths" % EVALUATION_LENGTHS_ENV
        ) from exc
    if not result or len(result) != len(set(result)):
        raise ValueError("%s must select unique evaluation lengths" % EVALUATION_LENGTHS_ENV)
    if any(value not in DEFAULT_EVALUATION_LENGTHS for value in result):
        raise ValueError("%s accepts only 320, 640, and 1280" % EVALUATION_LENGTHS_ENV)
    return result


def alpha_partitions(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Tuple[str, Tuple[int, ...]], ...]:
    """Reuse the established batch/ID selectors with a bounded 20-formula lane."""

    selected = selected_alpha_batches(environ)
    partitions = []
    for batch_name, ids in selected:
        for offset in range(0, len(ids), BATCH_SIZE):
            partitions.append((batch_name, tuple(ids[offset : offset + BATCH_SIZE])))
    if not partitions:
        raise ValueError("the live Alpha101 matrix requires at least one selected formula")
    return tuple(partitions)


def positive_target_frames(periods: int) -> Dict[str, pd.DataFrame]:
    """Use five assets from the accepted complete synthetic Alpha101 fixture."""

    full = make_positive_fixture(periods)
    assets = tuple(full)[:TARGET_COUNT]
    frames = {asset: full[asset].copy() for asset in assets}
    grid = tuple(frames[assets[0]].index)
    for asset_index, (asset, frame) in enumerate(frames.items()):
        if tuple(frame.index) != grid:
            raise AssertionError("Alpha101 target fixture grids differ")
        required = set(TARGET_LINE_FIELDS)
        if not required.issubset(frame.columns):
            raise AssertionError(
                "Alpha101 fixture misses complete live fields: %r"
                % sorted(required - set(frame.columns))
            )
        # Dollar volume is a separately supplied positive source field. Use a
        # deterministic independent per-bar source so long moving averages
        # retain enough rank variation for Alpha096/097's nested correlation
        # windows. Never infer this field from OHLC, VWAP, or share volume.
        source = random.Random(50_101 + asset_index)
        frame["dollar_volume"] = [
            3_200.0 + asset_index * 280.0 + source.uniform(-1_300.0, 1_300.0)
            for _sequence in range(len(frame))
        ]
        if any(
            not math.isfinite(float(value)) or float(value) <= 0.0
            for value in frame["dollar_volume"]
        ):
            raise AssertionError("synthetic dollar_volume must remain finite and positive")
        if not any(
            float(vwap)
            != (float(row.open) + float(row.high) + float(row.low) + float(row.close)) / 4.0
            for vwap, row in zip(frame["vwap"], frame.itertuples())
        ):
            raise AssertionError("synthetic VWAP must be an independently supplied field")
        if any(
            math.isclose(
                float(dollar_volume),
                float(vwap) * float(volume),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            for dollar_volume, vwap, volume in zip(
                frame["dollar_volume"], frame["vwap"], frame["volume"]
            )
        ):
            raise AssertionError("synthetic dollar_volume must be independent of VWAP × volume")
    return frames


def field_bindings_for_alpha(indicator: type) -> Mapping[str, Any]:
    """Bind production Alpha101 aliases to exact target lines and derivations."""

    bindings = {}
    for alias in tuple(indicator.formula_fields):
        if alias == "dollar_volume":
            bindings[alias] = "feed:target:dollar_volume"
        elif alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": int(alias[3:]),
            }
        else:
            bindings[alias] = "feed:target:%s" % alias
    return MappingProxyType(bindings)


def _utc_datetime(point: Any) -> datetime:
    if hasattr(point, "to_pydatetime"):
        point = point.to_pydatetime()
    if point.tzinfo is None or point.utcoffset() is None:
        raise AssertionError("Alpha101 synthetic grid must be timezone-aware")
    return point.astimezone(UTC)


def _slot_events(
    symbol: str,
    slots: Sequence[LiveCalendarSlot],
    frame: Optional[pd.DataFrame],
) -> Tuple[Mapping[str, Any], ...]:
    events = []
    for sequence, slot in enumerate(slots, start=1):
        if frame is None:
            close = 3_000.0 + sequence * 0.37 + math.sin(sequence * 0.13) * 3.0
            open_value = close + math.sin(sequence * 0.17) * 0.21
            values = {
                "open": open_value,
                "high": max(open_value, close) + 0.4,
                "low": min(open_value, close) - 0.35,
                "close": close,
                "volume": 2_000_000.0 + sequence * 257.0,
                "openinterest": 0.0,
            }
        else:
            row = frame.iloc[sequence - 1]
            values = {name: float(getattr(row, name)) for name in BASE_LINE_FIELDS}
            values.update({name: float(getattr(row, name)) for name in EXTRA_LINE_FIELDS})
        event = {
            "instrument": symbol,
            "symbol": symbol,
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "effective_at": slot.close_time,
            "available_at": slot.close_time + timedelta(seconds=AVAILABILITY_DELAY_SECONDS),
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": CLOCK_DOMAIN_ID,
            "connection_generation": "alpha101-source-generation-1",
            "bar_sequence": sequence,
            "bar_id": "%s-%06d" % (symbol, sequence),
            "present": True,
            "missing_fields": (),
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "iteration50-alpha101-live-matrix-fixture",
        }
        event.update(values)
        events.append(MappingProxyType(event))
    return tuple(events)


def _same_number(left: Any, right: Any) -> bool:
    left_value, right_value = float(left), float(right)
    if math.isnan(left_value) or math.isnan(right_value):
        return math.isnan(left_value) and math.isnan(right_value)
    return left_value == right_value


def _result_reason_name(instance: FactorIndicator, feed: Any, output_name: str) -> Optional[str]:
    """Translate the exact current factor result reason line independently."""

    try:
        target_index = next(
            index for index, candidate in enumerate(instance.target_datas) if candidate is feed
        )
        result_line = instance._result_lines[target_index]
    except (AttributeError, IndexError, StopIteration, TypeError) as exc:
        raise AssertionError("live result reason is not bound to the exact target feed") from exc
    if isinstance(result_line, (tuple, list)):
        result_line = result_line[target_index] if target_index < len(result_line) else None
    reason_line = getattr(result_line, "_factor_research_reason_line", None)
    if reason_line is None:
        output_line = instance.outputs[feed][output_name]
        reason_line = getattr(output_line, "_factor_research_reason_line", None)
    if reason_line is None:
        return None
    try:
        raw = float(reason_line[0])
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError) as exc:
        raise AssertionError("live result reason line is unreadable") from exc
    if not math.isfinite(raw) or not raw.is_integer():
        raise AssertionError("live result reason line is not a finite integer code")
    from backtrader.research.operators import REASON_NAMES

    reason = REASON_NAMES.get(int(raw))
    if reason is None:
        raise AssertionError("live result reason line contains an unknown code")
    return None if reason == "READY" else reason


class Alpha101LiveMatrixStrategy(bt.Strategy):
    """Ordinary Strategy which reads only completed LiveFactorSet snapshots."""

    params = (("cohort", None), ("plan", None), ("clock", None))

    def __init__(self) -> None:
        self.feed_by_name = {data._name: data for data in self.datas}
        self.live_factor_set = LiveFactorSet.bind(
            self.p.plan,
            self.feed_by_name,
            cohort=self.p.cohort,
        )
        self.readings = []
        self._factor_names = tuple(self.p.plan.factors)

    def _capture(self) -> None:
        batch = self.p.cohort.current_batch()
        if batch is None or batch.status != "COMPLETE":
            raise AssertionError("ordinary Strategy callback ran without a complete cohort batch")
        clock_now = self.p.clock.utc_now()
        if batch.available_at > clock_now:
            raise AssertionError("Strategy callback preceded the batch available_at")
        if len(batch.members) != len(self.feed_by_name):
            raise AssertionError("complete batch omitted a registered auxiliary or target feed")

        receipts = {}
        line_values = {}
        for name, feed in self.feed_by_name.items():
            member = self.p.cohort.member_for_feed(feed)
            if member is None:
                raise AssertionError("Strategy feed is not an exact registered cohort member")
            receipt = batch.members.get(member.member_id)
            if receipt is None or receipt.feed_ref is not feed:
                raise AssertionError("complete batch receipt does not bind the exact feed")
            if receipt.close_time != batch.close_time or receipt.available_at > clock_now:
                raise AssertionError("feed receipt time is not causally available at callback")
            if receipt.source_role != "live" or receipt.present is not True:
                raise AssertionError("full Alpha101 live matrix must use present live source rows")
            if receipt.complete is not True or receipt.quality != "GOOD":
                raise AssertionError("full Alpha101 live matrix received a non-GOOD row")
            receipts[name] = receipt
            member = self.p.cohort.member_for_feed(feed)
            line_values[name] = {
                field: float(getattr(feed, field)[0]) for field in member.line_fields
            }

        snapshot = self.live_factor_set.snapshot()
        if (
            snapshot.batch_complete is not True
            or snapshot.batch_id != batch.batch_id
            or snapshot.available_at != batch.available_at
        ):
            raise AssertionError("LiveFactorSet snapshot does not match the exact current batch")

        values_by_factor = {}
        reasons_by_factor = {}
        for factor_name in self._factor_names:
            result = snapshot.factors[factor_name]
            if tuple(result.values) != tuple(self.p.plan.targets):
                raise AssertionError("auxiliary benchmark entered the Alpha101 target pool")
            group_instances = self.live_factor_set.factor_instances[factor_name]
            if tuple(group_instances) != ("default",):
                raise AssertionError("Alpha101 target group differs from the batch group")
            instance = group_instances["default"]
            target_values = {}
            target_reasons = {}
            for target in self.p.plan.targets:
                output = result.values[target]
                output_value = float(output.value)
                feed = self.feed_by_name[target]
                line_value = float(instance.outputs[feed][result.panel_line][0])
                if not _same_number(output_value, line_value):
                    raise AssertionError(
                        "%s snapshot differs from its ordinary FactorIndicator line for %s"
                        % (factor_name, target)
                    )
                line_reason = _result_reason_name(instance, feed, result.panel_line)
                if output.reason != line_reason:
                    raise AssertionError(
                        "%s snapshot reason differs from its exact FactorIndicator reason line "
                        "for %s: %r != %r" % (factor_name, target, output.reason, line_reason)
                    )
                expected_available = (
                    output.present is True
                    and output.complete is True
                    and output.quality == "GOOD"
                    and math.isfinite(output_value)
                    and line_reason is None
                )
                expected_status = "OUTPUT_AVAILABLE" if expected_available else "OUTPUT_UNAVAILABLE"
                actual_status = getattr(output.status, "value", output.status)
                if actual_status != expected_status:
                    raise AssertionError(
                        "%s snapshot status disagrees with its value/reason for %s: %r"
                        % (factor_name, target, actual_status)
                    )
                receipt = receipts[target]
                if (
                    output.present is not receipt.present
                    or output.complete is not receipt.complete
                    or output.quality != receipt.quality
                ):
                    raise AssertionError(
                        "%s snapshot quality metadata differs from the exact receipt for %s"
                        % (factor_name, target)
                    )
                target_values[target] = output_value
                target_reasons[target] = output.reason
            values_by_factor[factor_name] = target_values
            reasons_by_factor[factor_name] = target_reasons

        if self.readings and batch.close_time <= self.readings[-1]["close_time"]:
            raise AssertionError("cohort callback did not advance to one strictly later slot")
        self.readings.append(
            {
                "batch_id": batch.batch_id,
                "close_time": batch.close_time,
                "available_at": batch.available_at,
                "callback_time": clock_now,
                "member_ids": tuple(batch.members),
                "readiness": snapshot.readiness,
                "values": values_by_factor,
                "reasons": reasons_by_factor,
                "receipts": receipts,
                "line_values": line_values,
            }
        )

    def prenext(self) -> None:
        self._capture()

    def nextstart(self) -> None:
        self._capture()

    def next(self) -> None:
        self._capture()

    def get_panel(self) -> Any:
        """Expose the actual snapshot values to the existing trace validator."""

        if not self.readings:
            raise AssertionError("live Alpha101 Strategy collected no complete batches")
        times = [record["close_time"] for record in self.readings]
        index = pd.MultiIndex.from_product(
            [times, list(self.p.plan.targets)], names=("time", "asset")
        )
        columns = {}
        for factor_name in self._factor_names:
            columns[factor_name] = [
                record["values"][factor_name][target]
                for record in self.readings
                for target in self.p.plan.targets
            ]
        return SimpleNamespace(
            factors=pd.DataFrame(columns, index=index, dtype="float64"),
            factor_order=self._factor_names,
        )


class FullGridFactorTraceView:
    """Adapt bounded live diagnostics to the existing full-grid graph checker.

    The production FactorIndicator keeps only its documented bounded call-time
    sample.  This test view supplies the full grid captured by the ordinary
    Strategy callback after independently checking the factor's total call
    count and retained sample against the same run.
    """

    def __init__(self, factor: FactorIndicator, grid: Sequence[datetime]) -> None:
        self._factor = factor
        self._factor_grid = tuple(grid)
        self._factor_call_times = tuple(grid)

    @property
    def __class__(self):  # the validator checks the production Alpha class
        return self._factor.__class__

    def __getattr__(self, name: str) -> Any:
        return getattr(self._factor, name)


class SnapshotPanelTraceView:
    """Let the shared validator read the rows emitted by LiveFactorSet.snapshot."""

    def __init__(self, strategy: Alpha101LiveMatrixStrategy) -> None:
        self._strategy = strategy

    def get_panel(self) -> Any:
        return self._strategy.get_panel()


def make_live_alpha_batch(
    frames: Mapping[str, pd.DataFrame],
    alpha_ids: Iterable[int],
    *,
    factor_mode: str,
) -> Tuple[Alpha101LiveMatrixStrategy, LiveBarCohort, ReplayClock, Tuple[datetime, ...]]:
    """Run selected production Alpha classes through real Feed/Cerebro/cohort."""

    if factor_mode not in ("native", "build"):
        raise ValueError("factor_mode must be native or build")
    ids = tuple(alpha_ids)
    if not ids:
        raise ValueError("at least one Alpha101 formula is required")
    targets = tuple(frames)
    if len(targets) != TARGET_COUNT:
        raise ValueError("the AC50-15b composition matrix requires exactly five targets")
    grid_values = tuple(next(iter(frames.values())).index)
    if not grid_values:
        raise ValueError("Alpha101 live matrix grid must not be empty")
    if any(tuple(frame.index) != grid_values for frame in frames.values()):
        raise ValueError("all five Alpha101 target feeds must share the exact grid")
    grid = tuple(_utc_datetime(point) for point in grid_values)
    if any(
        (right - left).total_seconds() != FREQUENCY_SECONDS for left, right in zip(grid, grid[1:])
    ):
        raise ValueError("daily Alpha101 target grid must advance in exact UTC days")

    member_names = targets + (BENCHMARK_NAME,)
    slots = tuple(
        LiveCalendarSlot(
            slot_id="alpha101-daily-%06d" % index,
            bucket_start=close_time - timedelta(seconds=FREQUENCY_SECONDS),
            close_time=close_time,
            trading_day=close_time.date().isoformat(),
            session_segment="regular",
        )
        for index, close_time in enumerate(grid)
    )
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
    max_window_bars = len(slots)
    cohort = LiveBarCohort(
        "alpha101-live-matrix-cohort",
        calendar,
        max_pending_slots=MAX_PENDING_SLOTS,
        max_window_bars=max_window_bars,
        wait_timeout_ns=WAIT_TIMEOUT_NS,
    )
    clock = ReplayClock(grid[0] - timedelta(seconds=1))
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    for name in member_names:
        is_target = name in frames
        events = _slot_events(name, slots, frames.get(name))
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=(),
            live_bars=events,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Days,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        cerebro.adddata(feed, name=name)
        feeds[name] = feed
        declared = TARGET_LINE_FIELDS if is_target else BASE_LINE_FIELDS
        cohort.register_member(
            "member-%s" % name,
            feed,
            instrument=name,
            source_ref=("synthetic-target-%s" % name)
            if is_target
            else "synthetic-named-benchmark-index",
            line_fields=declared,
            raw_fields=declared + ("effective_at",),
            numeric_fields=declared,
        )

    factors = {}
    for alpha_id in ids:
        factor_name = alpha_name(alpha_id)
        indicator = get_alpha(alpha_id)
        factors[factor_name] = FactorSpec(
            name=factor_name,
            indicator=indicator,
            panel_line="factor",
            field_bindings=field_bindings_for_alpha(indicator),
            mode=factor_mode,
        )
    plan = LiveFactorPlan(
        plan_id="alpha101-live-matrix-%s" % factor_mode,
        targets=targets,
        groups=dict.fromkeys(targets, "default"),
        factors=factors,
        calendar_id=CALENDAR_ID,
        frequency=FREQUENCY,
        warmup_min_bars=WARMUP_BARS,
        max_pending_slots=MAX_PENDING_SLOTS,
        max_window_bars=max_window_bars,
        wait_timeout_ns=WAIT_TIMEOUT_NS,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
        allow_history_prewarm=False,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(Alpha101LiveMatrixStrategy, cohort=cohort, plan=plan, clock=clock)
    strategy = cerebro.run()[0]
    if set(strategy.feed_by_name) != set(member_names):
        raise AssertionError(
            "ordinary Strategy did not receive the exact five targets and benchmark"
        )
    if tuple(strategy.p.plan.targets) != targets:
        raise AssertionError("named benchmark altered the immutable target pool")
    return strategy, cohort, clock, grid


def validate_live_run(
    strategy: Alpha101LiveMatrixStrategy,
    cohort: LiveBarCohort,
    clock: ReplayClock,
    frames: Mapping[str, pd.DataFrame],
    alpha_ids: Iterable[int],
    grid: Sequence[datetime],
) -> Mapping[str, FullGridFactorTraceView]:
    """Check real delivery, causal availability, call coverage and bounded samples."""

    ids = tuple(alpha_ids)
    expected_closes = tuple(grid)
    if tuple(record["close_time"] for record in strategy.readings) != expected_closes:
        raise AssertionError(
            "ordinary Strategy callback grid differs from the planned finite calendar"
        )
    if len(strategy.readings) != len(expected_closes):
        raise AssertionError(
            "ordinary Strategy did not receive exactly one callback per cohort batch"
        )
    if cohort.current_batch() is None or cohort.current_batch().status != "COMPLETE":
        raise AssertionError("finite Alpha101 run did not finish on a complete batch")
    if not clock.waits:
        raise AssertionError(
            "causal live replay did not wait for source availability or planned closes"
        )

    traces = {}
    for row_index, record in enumerate(strategy.readings):
        if record["available_at"] < record["close_time"]:
            raise AssertionError("source available_at precedes the completed bar close")
        if record["available_at"] > record["callback_time"]:
            raise AssertionError("callback was delivered before source available_at")
        if record["callback_time"] - record["close_time"] > timedelta(seconds=30):
            raise AssertionError("live cohort callback exceeded its configured freshness window")
        for asset, frame in frames.items():
            receipt = record["receipts"][asset]
            raw_values = receipt.envelope.raw_values
            row = frame.iloc[row_index]
            if raw_values["effective_at"] != record["close_time"]:
                raise AssertionError("synthetic PIT effective time differs from the planned close")
            if receipt.available_at != record["close_time"] + timedelta(
                seconds=AVAILABILITY_DELAY_SECONDS
            ):
                raise AssertionError("available_at did not preserve the synthetic source delay")
            for field in TARGET_LINE_FIELDS:
                if not _same_number(raw_values[field], float(getattr(row, field))):
                    raise AssertionError(
                        "sealed source field %s differs for %s at %s"
                        % (field, asset, record["close_time"].isoformat())
                    )
            for field in EXTRA_LINE_FIELDS:
                if not _same_number(record["line_values"][asset][field], raw_values[field]):
                    raise AssertionError(
                        "real BtApiFeed line %s differs from its sealed raw source" % field
                    )
        benchmark = record["receipts"][BENCHMARK_NAME]
        if benchmark.source_ref != "synthetic-named-benchmark-index":
            raise AssertionError("named synthetic benchmark provenance was lost")
        if benchmark.close_time != record["close_time"]:
            raise AssertionError("named benchmark is not aligned to the common planned close")
        if BENCHMARK_NAME in strategy.p.plan.targets:
            raise AssertionError("named benchmark incorrectly expanded factor targets")

    for alpha_id in ids:
        name = alpha_name(alpha_id)
        if name not in strategy.live_factor_set.factor_instances:
            raise AssertionError("live FactorIndicator missing production Alpha%d" % alpha_id)
        instance = strategy.live_factor_set.factor_instances[name]["default"]
        diagnostics = instance.lifecycle_diagnostics
        if diagnostics["call_count"] != len(grid):
            raise AssertionError(
                "Alpha%d FactorIndicator callback count is %r, expected %d"
                % (alpha_id, diagnostics["call_count"], len(grid))
            )
        sample = tuple(diagnostics["call_times"])
        expected_sample = tuple(grid[-len(sample) :]) if sample else ()
        if sample != expected_sample:
            # The strategy callback carries exact batch close times; compare
            # against the FactorIndicator's actual retained UTC sample after
            # normalizing pandas/Python datetime identities.
            normalized_sample = tuple(_utc_datetime(point) for point in sample)
            normalized_expected = tuple(_utc_datetime(point) for point in expected_sample)
            if normalized_sample != normalized_expected:
                raise AssertionError(
                    "Alpha%d bounded callback sample differs from live batches" % alpha_id
                )
        if len(grid) > len(sample) and not diagnostics.get("call_times_truncated", False):
            raise AssertionError(
                "live FactorIndicator did not report bounded diagnostics truncation"
            )
        for nested in FactorStrategy._factor_tree(instance):
            if isinstance(nested, FactorIndicator):
                nested_diagnostics = nested.lifecycle_diagnostics
                if nested_diagnostics["call_count"] != len(grid):
                    raise AssertionError(
                        "Alpha%d nested FactorIndicator callback count is incomplete" % alpha_id
                    )
        traces[name] = FullGridFactorTraceView(instance, grid)

    last = strategy.readings[-1]
    if getattr(last["readiness"], "value", last["readiness"]) != "LIVE_READY":
        raise AssertionError(
            "final full-history live Alpha101 snapshot is not LIVE_READY: %r" % (last["readiness"],)
        )
    return MappingProxyType(traces)


def materialize_live_presence_for_graph(strategy: Alpha101LiveMatrixStrategy) -> None:
    """Expose sealed live presence history to the static graph comparator.

    The live `_PresenceLine` is driven by each exact published receipt, so its
    construction-time `_present` tuple is empty. Batch inputs carry an aligned
    tuple instead. After execution, copy the receipt-derived history into that
    diagnostic tuple so the existing graph comparator can compare equivalent
    membership signatures. This runs only after live values/reasons were
    validated and cannot affect indicator calculation.
    """

    feed_names = {id(feed): name for name, feed in strategy.feed_by_name.items()}
    expected_by_target = {name: [] for name in strategy.p.plan.targets}
    for row in strategy.readings:
        for target in strategy.p.plan.targets:
            receipt = row["receipts"].get(target)
            if receipt is None:
                raise AssertionError("live graph lacks a target's sealed receipt")
            if receipt.complete is not True or receipt.quality not in ("GOOD", "MISSING"):
                raise AssertionError("live graph receipt is not a complete validated event")
            expected_by_target[target].append(
                receipt.present is True and receipt.quality == "GOOD" and not receipt.missing_fields
            )

    for groups in strategy.live_factor_set.factor_instances.values():
        for instance in groups.values():
            member_lines = tuple(instance.formula_members)
            target_datas = tuple(instance._factor_target_datas)
            if len(member_lines) != len(target_datas):
                raise AssertionError("live graph membership does not cover every target")
            for data, line in zip(target_datas, member_lines):
                target = feed_names.get(id(data))
                if target not in expected_by_target:
                    raise AssertionError("live graph presence is bound to a non-target feed")
                owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
                if type(owner) is not _PresenceLine or owner.p.cohort is not strategy.p.cohort:
                    raise AssertionError("live graph membership is not cohort receipt-backed")
                owner._present = tuple(expected_by_target[target])


def snapshot_panel_trace_view(strategy: Alpha101LiveMatrixStrategy) -> SnapshotPanelTraceView:
    return SnapshotPanelTraceView(strategy)


def assert_evaluation_witness(
    alpha_id: int,
    expected: Sequence[Sequence[float]],
    *,
    evaluation_bars: int,
    warmup_start: int,
) -> Mapping[str, int]:
    """Require finite, varying independent output inside the scored suffix."""

    if evaluation_bars < 1 or len(expected) < evaluation_bars:
        raise AssertionError("Alpha101 witness suffix is not present in the oracle grid")
    evaluation_start = len(expected) - evaluation_bars
    if evaluation_start < warmup_start:
        raise AssertionError("evaluation suffix began before formula and explicit warmup")
    suffix = [float(value) for row in expected[evaluation_start:] for value in row]
    finite = [value for value in suffix if math.isfinite(value)]
    distinct = {value.hex() for value in finite}
    if not finite:
        raise AssertionError(
            "Alpha%d has no finite independent oracle witness in evaluation T=%d"
            % (alpha_id, evaluation_bars)
        )
    if len(distinct) < 2:
        raise AssertionError(
            "Alpha%d evaluation T=%d has no nontrivial varying finite witness"
            % (alpha_id, evaluation_bars)
        )
    return {"finite_values": len(finite), "distinct_finite_values": len(distinct)}


def evaluation_start_for(alpha_ids: Iterable[int], periods: int) -> Tuple[int, int]:
    """Return total bars and the boundary after max formula H plus explicit 30 warmup."""

    from tests.test_utils.alpha101_full_reference import history_h

    ids = tuple(alpha_ids)
    if not ids:
        raise ValueError("at least one Alpha101 ID is required")
    maximum_h = max(history_h(alpha_id) for alpha_id in ids)
    evaluation_start = maximum_h + WARMUP_BARS
    return evaluation_start + periods, evaluation_start


__all__ = (
    "BENCHMARK_NAME",
    "DEFAULT_EVALUATION_LENGTHS",
    "EVALUATION_LENGTHS_ENV",
    "WARMUP_BARS",
    "alpha_partitions",
    "assert_evaluation_witness",
    "evaluation_lengths",
    "evaluation_start_for",
    "field_bindings_for_alpha",
    "make_live_alpha_batch",
    "materialize_live_presence_for_graph",
    "positive_target_frames",
    "snapshot_panel_trace_view",
    "validate_live_run",
)
