"""Alpha003 parity across the batch engine and strict live cohort feeds.

The test binds the production Alpha003 class through its normal FactorSpec and
LiveFactorSet paths.  The runnext/runonce research lanes and the live cohort
lane all use real Cerebro execution; only the live source events and replay
clock are deterministic test leaves.  Expected values come from the
independent paper-formula oracle, never from the production Alpha003 graph.
"""

from __future__ import annotations

import math
from types import MappingProxyType, SimpleNamespace
from datetime import datetime, timedelta, timezone

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research import operators
from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.research.alpha101 import get_alpha
from tests.test_utils.alpha101_native_harness import (
    assert_lifecycle,
    assert_matrix_matches,
    make_positive_fixture,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs, validate_factor_trace


_UTC = timezone.utc
_ASSET_ORDER = tuple("asset-%d" % index for index in range(6))
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_HISTORY_LENGTHS = (320, 640, 1280)
_WARMUP_BARS = 30


class _ReplayClock:
    """Small deterministic clock injected into the real cohort scheduler."""

    def __init__(self, now: datetime):
        self.now = now
        self._monotonic_ns = 1_000_000_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self._monotonic_ns

    def wait(self, timeout_seconds):
        timeout = max(0.0, float(timeout_seconds))
        self.waits.append(timeout)
        self._monotonic_ns += max(1, int(timeout * 1_000_000_000))
        if timeout:
            self.now += timedelta(seconds=timeout)


class _LiveAlpha003Capture(bt.Strategy):
    """Capture the public LiveFactorSet snapshot from ordinary callbacks."""

    params = (("cohort", None), ("plan", None), ("target_order", ()))

    def __init__(self):
        feeds = {data._name: data for data in self.datas}
        self.live_factor_set = LiveFactorSet.bind(self.p.plan, feeds, cohort=self.p.cohort)
        self.target_order = tuple(self.p.target_order)
        self.snapshots = []
        self.factor_callback_times = []
        groups = self.live_factor_set.factor_instances["alpha003"]
        assert tuple(groups) == ("default",)
        self._observe_factor_callbacks(groups["default"])

    def _observe_factor_callbacks(self, factor):
        """Record each real FactorIndicator callback before bounded diagnostics trim it."""
        record = factor._record_factor_call
        observed = self.factor_callback_times
        target = factor._factor_target_datas[0]

        def record_and_observe():
            record()
            current = target.datetime.datetime(0)
            observed.append(current.replace(tzinfo=_UTC))

        factor._record_factor_call = record_and_observe

    def prenext(self):
        self._capture()

    def nextstart(self):
        self._capture()

    def next(self):
        self._capture()

    def _capture(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factor_set.snapshot()
        assert batch.close_time == snapshot.close_time
        assert len(batch.members) == len(self.datas)
        assert len({len(data) for data in self.datas}) == 1
        assert all(
            data.datetime.datetime(0) == batch.close_time.replace(tzinfo=None)
            for data in self.datas
        )
        self.snapshots.append(snapshot)

    def get_panel(self):
        """Adapt captured public snapshots to the shared trace-validator shape."""
        index = []
        values = []
        for snapshot in self.snapshots:
            block = snapshot.factors["alpha003"]
            for asset in self.target_order:
                index.append((snapshot.close_time, asset))
                values.append(float(block.values[asset].value))
        panel_index = pd.MultiIndex.from_tuples(index, names=("time", "asset"))
        factors = pd.DataFrame({"alpha003": values}, index=panel_index)
        return SimpleNamespace(factors=factors)


def _live_alpha003_plan(
    targets,
    *,
    calendar,
    mode,
    max_pending_slots,
    max_window_bars,
    wait_timeout_ns,
    max_future_skew_seconds,
):
    """Build the ordinary immutable live factor contract for Alpha003."""
    return LiveFactorPlan(
        plan_id="alpha003-live-parity-%s" % mode,
        targets=targets,
        factors={
            "alpha003": FactorSpec(
                name="alpha003",
                indicator=get_alpha(3),
                panel_line="factor",
                field_bindings={
                    "open": "feed:target:open",
                    "volume": "feed:target:volume",
                },
                mode=mode,
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=_WARMUP_BARS,
        max_pending_slots=max_pending_slots,
        max_window_bars=max_window_bars,
        wait_timeout_ns=wait_timeout_ns,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=max_future_skew_seconds,
        allow_history_prewarm=True,
    )


def _minute_frames(periods):
    source = make_positive_fixture(periods)
    grid = pd.date_range("2025-01-02 09:31:00", periods=periods, freq="min", tz="UTC")
    frames = {}
    for asset, frame in source.items():
        copied = frame.copy(deep=True)
        copied.index = grid
        frames[asset] = copied
    return frames


def _calendar(targets, grid):
    members = {asset: "member-%s" % asset for asset in targets}
    slots = []
    for index, point in enumerate(grid):
        close_time = point.to_pydatetime()
        bucket_start = close_time - timedelta(minutes=1)
        trading_day = close_time.strftime("%Y%m%d")
        sessions = {
            members[asset]: LiveCalendarMemberSession(
                trading_day=trading_day,
                session_segment="regular",
            )
            for asset in targets
        }
        slots.append(
            LiveCalendarSlot(
                slot_id="alpha003-slot-%d" % index,
                bucket_start=bucket_start,
                close_time=close_time,
                trading_day=trading_day,
                session_segment="regular",
                member_sessions=MappingProxyType(sessions),
            )
        )
    return (
        LiveCohortCalendar(
            calendar_id="alpha003-live-parity-v1",
            version="v1",
            epoch_id=1,
            frequency="1min",
            frequency_seconds=60,
            timezone_id="UTC",
            clock_domain_id="alpha003-replay-clock-v1",
            session_semantics="alpha003-replay-session-v1",
            slots=tuple(slots),
        ),
        members,
    )


def _bar_events(frames, asset, *, arrival_delay=None):
    frame = frames[asset]
    events = []
    for sequence, point in enumerate(frame.index, start=1):
        close_time = point.to_pydatetime()
        delay = 0.0 if arrival_delay is None else float(arrival_delay(asset, sequence - 1))
        available_at = close_time + timedelta(seconds=delay)
        row = frame.iloc[sequence - 1]
        events.append(
            MappingProxyType(
                {
                    "instrument": asset,
                    "symbol": asset,
                    "timestamp": close_time.timestamp(),
                    "datetime": close_time,
                    "bucket_start": close_time - timedelta(minutes=1),
                    "bucket_end": close_time,
                    "available_at": available_at,
                    "trading_day": close_time.strftime("%Y%m%d"),
                    "session_segment": "regular",
                    "timezone_id": "UTC",
                    "clock_domain_id": "alpha003-replay-clock-v1",
                    "connection_generation": "generation-1",
                    "bar_sequence": sequence,
                    "bar_id": "%s-bar-%d" % (asset, sequence),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "openinterest": float(row["openinterest"]),
                    "present": True,
                    "complete": True,
                    "quality": "GOOD",
                    "quality_flags": (),
                    "source": "alpha003-live-parity-fixture",
                }
            )
        )
    return tuple(events)


def _run_live(
    frames,
    *,
    mode,
    target_order=None,
    feed_order=None,
    registration_order=None,
    history_bars=0,
    arrival_delay=None,
    max_future_skew_seconds=0.0,
):
    targets = tuple(target_order or frames)
    feed_order = tuple(feed_order or targets)
    registration_order = tuple(registration_order or targets)
    grid = tuple(next(iter(frames.values())).index)
    calendar, member_ids = _calendar(targets, grid)
    cohort = LiveBarCohort(
        "alpha003-live-parity",
        calendar,
        max_pending_slots=2,
        max_window_bars=len(grid),
        wait_timeout_ns=5_000_000_000,
    )
    clock = _ReplayClock(grid[0].to_pydatetime())
    events = {asset: _bar_events(frames, asset, arrival_delay=arrival_delay) for asset in targets}
    feeds = {}
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=0,
        preload=False,
        runonce=False,
    )
    for asset in feed_order:
        raw_events = events[asset]
        feed = bt.feeds.BtApiFeed(
            dataname=asset,
            historical_bars=raw_events[:history_bars],
            live_bars=raw_events[history_bars:],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)

    for asset in registration_order:
        cohort.register_member(
            member_ids[asset],
            feeds[asset],
            instrument=asset,
            source_ref="feed-%s" % asset,
            line_fields=_OHLCV_FIELDS,
            raw_fields=_OHLCV_FIELDS,
            numeric_fields=_OHLCV_FIELDS,
        )

    plan = _live_alpha003_plan(
        targets,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=len(grid),
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=max_future_skew_seconds,
    )
    assert plan.factors["alpha003"].indicator is get_alpha(3)
    assert plan.factors["alpha003"].mode == mode
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _LiveAlpha003Capture,
        cohort=cohort,
        plan=plan,
        target_order=targets,
    )
    strategy = cerebro.run()[0]
    assert len(strategy.snapshots) == len(grid)
    assert all(snapshot.batch_complete for snapshot in strategy.snapshots)
    assert all(feed.live_bar_cohort is cohort for feed in feeds.values())
    assert all(
        type(event) is type(MappingProxyType({})) for group in events.values() for event in group
    )
    for asset, feed in feeds.items():
        receipts = cohort.complete_window_bars(feed, _OHLCV_FIELDS, len(grid))
        assert len(receipts) == len(grid), asset
        for row, (receipt, point) in enumerate(zip(receipts, grid)):
            assert receipt.close_time == point.to_pydatetime(), (asset, row)
            assert receipt.slot_index == row, (asset, row)
            assert receipt.source_role == ("history" if row < history_bars else "live")
            assert receipt.present is True and receipt.complete is True
            assert receipt.quality == "GOOD"
    return strategy, cohort, feeds


def _factor_for_live(strategy):
    groups = strategy.live_factor_set.factor_instances["alpha003"]
    assert tuple(groups) == ("default",)
    return groups["default"]


class _ObservedFactorTraceView:
    """Adapt bounded live factor diagnostics to validators using actual callbacks.

    The callback times are recorded by the strategy-side observer installed on
    the real factor's ``_record_factor_call`` entry.  The production factor
    retains its fixed-size diagnostic deque; this view supplies the already
    observed full sequence only to the existing full-grid trace comparators.
    """

    def __init__(self, factor, callback_times):
        self._delegate = factor
        self._factor_call_times = tuple(callback_times)

    @property
    def __class__(self):
        return self._delegate.__class__

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def _factor_trace_view(factor, strategy, grid, *, label):
    expected_times = tuple(point.to_pydatetime() for point in grid)
    observed_times = tuple(strategy.factor_callback_times)
    assert observed_times == expected_times, (label, "actual factor callback timestamps")
    assert factor._factor_call_count == len(expected_times), (
        label,
        "actual factor callback count",
        factor._factor_call_count,
    )
    diagnostics = factor.lifecycle_diagnostics
    assert diagnostics["call_count"] == len(expected_times)
    assert diagnostics["call_times_truncated"] is (
        len(expected_times) > len(diagnostics["call_times"])
    )
    return _ObservedFactorTraceView(factor, observed_times)


def _snapshot_matrix(strategy, targets):
    return [
        [float(snapshot.factors["alpha003"].values[asset].value) for asset in targets]
        for snapshot in strategy.snapshots
    ]


def _assert_expected_reason_lines(factor, assets, expected):
    rows = len(expected)
    ready = float(operators.OperatorReason.READY)
    not_ready = float(operators.OperatorReason.NOT_READY)
    domain_error = float(operators.OperatorReason.DOMAIN_ERROR)
    expected_keys = {"rank_open", "rank_volume"}
    expected_keys.update("correlation10_%d" % index for index in range(len(assets)))
    expected_keys.update("negate_%d" % index for index in range(len(assets)))
    assert set(factor._nodes) == expected_keys, (
        "Alpha003 must expose both rank panels and every per-asset correlation/final node",
        sorted(factor._nodes),
    )
    assert len(factor._nodes) == 2 + 2 * len(assets)
    for rank_name in ("rank_open", "rank_volume"):
        rank = factor._nodes[rank_name]
        assert isinstance(rank, operators.CrossSectionalRank)
        for target in factor.target_datas:
            output = rank.outputs[target]
            values = [float(value) for value in output.value.array]
            reasons = [float(value) for value in output.reason.array]
            assert len(values) == rows, (rank_name, target._name, "value rows")
            assert len(reasons) == rows
            assert reasons == [ready] * rows, (rank_name, target._name)

    correlation_type = operators.RollingCorrelation
    assert len(
        [
            node
            for node in factor._nodes.values()
            if getattr(node, "_logical_operator_type", type(node)) is correlation_type
        ]
    ) == len(assets)
    for asset_index, asset in enumerate(assets):
        correlation = factor._nodes["correlation10_%d" % asset_index]
        negate = factor._nodes["negate_%d" % asset_index]
        for label, node in (("correlation10", correlation), ("final", negate)):
            values = [float(value) for value in node.lines.value.array]
            reasons = [float(value) for value in node.lines.reason.array]
            assert len(values) == rows, (label, asset, "value rows")
            assert len(reasons) == rows, (label, asset, "reason rows")
        expected_reasons = [
            not_ready
            if row < 9
            else ready
            if math.isfinite(float(expected[row][asset_index]))
            else domain_error
            for row in range(rows)
        ]
        correlation_reasons = [float(value) for value in correlation.lines.reason.array]
        negate_reasons = [float(value) for value in negate.lines.reason.array]
        assert correlation_reasons == expected_reasons, ("correlation10", asset)
        assert negate_reasons == expected_reasons, ("negate", asset)


def _assert_live_snapshot_projection(strategy, assets, grid, expected, *, label):
    actual = _snapshot_matrix(strategy, assets)
    assert_matrix_matches(actual, expected, label=label)
    finite_count = sum(math.isfinite(value) for row in actual for value in row)
    assert finite_count >= 100, "%s needs at least 100 finite live values" % label
    for row, snapshot in enumerate(strategy.snapshots):
        assert snapshot.close_time == grid[row].to_pydatetime(), (label, row)
        assert snapshot.available_at >= snapshot.close_time, (label, row)
        for column, asset in enumerate(assets):
            output = snapshot.factors["alpha003"].values[asset]
            value = float(expected[row][column])
            expected_reason = (
                "NOT_READY" if row < 9 else "DOMAIN_ERROR" if not math.isfinite(value) else None
            )
            assert output.reason == expected_reason, (label, row, asset)
            assert output.status.value == (
                "OUTPUT_AVAILABLE" if expected_reason is None else "OUTPUT_UNAVAILABLE"
            ), (label, row, asset)


def _validate_live(strategy, frames, *, label):
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    factor = _factor_for_live(strategy)
    assert factor.factor_mode == strategy.p.plan.factors["alpha003"].mode
    trace_factor = _factor_trace_view(factor, strategy, grid, label=label)
    report = validate_factor_trace(trace_factor, 3, frames, assets, grid, strategy=strategy)
    assert report["failures"] == [], "%s: %r" % (label, report["failures"][:20])
    # The independent oracle walks four semantic AST operations.  Separately,
    # _assert_expected_reason_lines requires 2 rank panels and both logical
    # per-asset branches, for 14 actual graph registrations with six assets.
    assert report["matched_nodes"] == 4, (label, report["matched_nodes"])
    _assert_expected_reason_lines(factor, assets, report["expected"])
    _assert_live_snapshot_projection(strategy, assets, grid, report["expected"], label=label)
    return report["expected"], factor


@pytest.mark.integration
def test_alpha003_live_native_t320_minimal_oracle_and_logical_nodes():
    """Exercise the first strict live lane before the full parity matrix."""
    frames = _minute_frames(320)
    grid = tuple(next(iter(frames.values())).index)
    strategy, _cohort, _feeds = _run_live(frames, mode="native")
    expected, factor = _validate_live(
        strategy,
        frames,
        label="minimal live native T320",
    )
    assert len(factor._nodes) == 14
    assert sum(math.isfinite(float(value)) for row in expected for value in row) >= 100
    assert tuple(strategy.factor_callback_times) == tuple(point.to_pydatetime() for point in grid)


def _assert_exact_matrix_equal(left, right, *, label):
    assert len(left) == len(right), label
    for row_index, (left_row, right_row) in enumerate(zip(left, right)):
        assert len(left_row) == len(right_row), (label, row_index)
        for column, (got, wanted) in enumerate(zip(left_row, right_row)):
            got, wanted = float(got), float(wanted)
            if math.isnan(wanted):
                assert math.isnan(got), (label, row_index, column)
            else:
                assert got == wanted, (label, row_index, column, got, wanted)


def _actual_node_arrays(node, target, *, panel):
    output = node.outputs[target] if panel else node.lines
    values = tuple(float(value) for value in output.value.array)
    reasons = tuple(float(value) for value in output.reason.array)
    return values, reasons


def _compare_alpha003_registered_nodes(left_factor, right_factor, assets, *, label):
    """Compare all rank, correlation and final nodes by exact registration key."""
    left_nodes = left_factor._nodes
    right_nodes = right_factor._nodes
    expected_keys = {"rank_open", "rank_volume"}
    expected_keys.update("correlation10_%d" % index for index in range(len(assets)))
    expected_keys.update("negate_%d" % index for index in range(len(assets)))
    assert set(left_nodes) == expected_keys, (label, "left node keys", sorted(left_nodes))
    assert set(right_nodes) == expected_keys, (label, "right node keys", sorted(right_nodes))

    for node_key in ("rank_open", "rank_volume"):
        left_node = left_nodes[node_key]
        right_node = right_nodes[node_key]
        assert isinstance(left_node, operators._PanelOperator)
        assert isinstance(right_node, operators._PanelOperator)
        for asset in assets:
            target_left = next(data for data in left_factor.target_datas if data._name == asset)
            target_right = next(data for data in right_factor.target_datas if data._name == asset)
            left_values, left_reasons = _actual_node_arrays(left_node, target_left, panel=True)
            right_values, right_reasons = _actual_node_arrays(right_node, target_right, panel=True)
            _assert_exact_matrix_equal(
                [left_values],
                [right_values],
                label="%s %s %s values" % (label, node_key, asset),
            )
            assert left_reasons == right_reasons, (label, node_key, asset, "reasons")

    for node_prefix in ("correlation10", "negate"):
        for index, asset in enumerate(assets):
            node_key = "%s_%d" % (node_prefix, index)
            left_values, left_reasons = _actual_node_arrays(left_nodes[node_key], None, panel=False)
            right_values, right_reasons = _actual_node_arrays(
                right_nodes[node_key], None, panel=False
            )
            _assert_exact_matrix_equal(
                [left_values],
                [right_values],
                label="%s %s %s values" % (label, node_key, asset),
            )
            assert left_reasons == right_reasons, (label, node_key, asset, "reasons")


@pytest.mark.integration
def test_alpha003_live_cohort_matches_independent_oracle_and_batch_paths():
    """Check the production graph at three horizons and both implementation modes."""
    for periods in _HISTORY_LENGTHS:
        frames = _minute_frames(periods)
        assets = tuple(frames)
        grid = tuple(next(iter(frames.values())).index)
        per_mode = {}

        for mode in ("native", "build"):
            batch_runs = {}
            for engine_name, runonce in (("runnext", False), ("runonce", True)):
                strategy = run_native_batch(
                    frames,
                    (3,),
                    runonce=runonce,
                    factor_mode=mode,
                    alpha_classes={3: get_alpha(3)},
                )
                assert_lifecycle(strategy, (3,), grid, alpha_classes={3: get_alpha(3)})
                factor = strategy.factor_instances["alpha3"]
                trace = validate_factor_trace(factor, 3, frames, assets, grid, strategy=strategy)
                assert trace["failures"] == [], "%s T%d %s: %r" % (
                    mode,
                    periods,
                    engine_name,
                    trace["failures"][:20],
                )
                # The independent formula trace reports four distinct AST
                # operations; the helper below separately requires both rank
                # panels and all twelve per-asset correlation/final nodes.
                assert trace["matched_nodes"] == 4, (
                    mode,
                    periods,
                    engine_name,
                    trace["matched_nodes"],
                )
                _assert_expected_reason_lines(factor, assets, trace["expected"])
                matrix = [
                    [
                        float(
                            strategy.get_panel().factors.at[
                                (point.to_pydatetime(), asset), "alpha3"
                            ]
                        )
                        for asset in assets
                    ]
                    for point in grid
                ]
                assert_matrix_matches(
                    matrix, trace["expected"], label="%s T%d %s" % (mode, periods, engine_name)
                )
                assert sum(math.isfinite(value) for row in matrix for value in row) >= 100
                batch_runs[engine_name] = strategy

            live_strategy, cohort, _feeds = _run_live(
                frames,
                mode=mode,
                target_order=assets,
            )
            live_expected, live_factor = _validate_live(
                live_strategy,
                frames,
                label="live %s T%d" % (mode, periods),
            )
            per_mode[mode] = {
                "batch": batch_runs,
                "live": live_strategy,
                "factor": live_factor,
                "expected": live_expected,
                "cohort": cohort,
            }
            batch_next_factor = batch_runs["runnext"].factor_instances["alpha3"]
            for engine_name in ("runnext", "runonce"):
                report = compare_factor_graphs(
                    batch_next_factor,
                    batch_runs[engine_name].factor_instances["alpha3"],
                    3,
                )
                assert report["equal"], "%s T%d batch %s: %r" % (
                    mode,
                    periods,
                    engine_name,
                    report["failures"][:20],
                )
            live_trace_factor = _factor_trace_view(
                live_factor,
                per_mode[mode]["live"],
                grid,
                label="graph comparison live %s T%d" % (mode, periods),
            )
            for engine_name in ("runnext", "runonce"):
                _compare_alpha003_registered_nodes(
                    batch_runs[engine_name].factor_instances["alpha3"],
                    live_trace_factor,
                    assets,
                    label="%s T%d %s-vs-live" % (mode, periods, engine_name),
                )
            assert len(live_strategy.snapshots) == periods
            assert all(
                snapshot.readiness is LiveFactorReadiness.LIVE_READY
                for snapshot in live_strategy.snapshots[_WARMUP_BARS - 1 :]
            )

        native_build = compare_factor_graphs(
            _factor_trace_view(
                per_mode["native"]["factor"],
                per_mode["native"]["live"],
                grid,
                label="native/build native graph T%d" % periods,
            ),
            _factor_trace_view(
                per_mode["build"]["factor"],
                per_mode["build"]["live"],
                grid,
                label="native/build build graph T%d" % periods,
            ),
            3,
        )
        assert native_build["equal"], "T%d native/build: %r" % (
            periods,
            native_build["failures"][:20],
        )

    # A future-only value and arrival-time change cannot rewrite already sealed
    # batches.  The suffix must still match its own independent formula oracle.
    causal_frames = _minute_frames(320)
    causal_grid = tuple(next(iter(causal_frames.values())).index)
    cut = 160
    changed = {asset: frame.copy(deep=True) for asset, frame in causal_frames.items()}
    for asset_index, asset in enumerate(tuple(changed)):
        frame = changed[asset]
        for row in range(cut, len(frame)):
            point = frame.index[row]
            frame.loc[point, "open"] = 100.0 + asset_index
            frame.loc[point, "volume"] = 1000.0 + (len(changed) - asset_index)
            frame.loc[point, "high"] = (
                max(float(frame.loc[point, "open"]), float(frame.loc[point, "close"])) + 0.5
            )
            frame.loc[point, "low"] = (
                min(float(frame.loc[point, "open"]), float(frame.loc[point, "close"])) - 0.5
            )
    for mode in ("native", "build"):
        baseline, _cohort, _feeds = _run_live(causal_frames, mode=mode)
        baseline_expected, _baseline_factor = _validate_live(
            baseline,
            causal_frames,
            label="causal baseline %s" % mode,
        )
        perturbed, _cohort, _feeds = _run_live(
            changed,
            mode=mode,
            arrival_delay=lambda asset, row: (
                (1 + _ASSET_ORDER.index(asset) % 3) if row >= cut else 0
            ),
            max_future_skew_seconds=5.0,
        )
        changed_expected, _changed_factor = _validate_live(
            perturbed,
            changed,
            label="causal future perturbation %s" % mode,
        )
        baseline_values = _snapshot_matrix(baseline, tuple(causal_frames))
        changed_values = _snapshot_matrix(perturbed, tuple(changed))
        _assert_exact_matrix_equal(
            baseline_values[:cut], changed_values[:cut], label="sealed causal prefix " + mode
        )
        for row in range(cut):
            for asset in tuple(causal_frames):
                left = baseline.snapshots[row].factors["alpha003"].values[asset]
                right = perturbed.snapshots[row].factors["alpha003"].values[asset]
                assert (left.status, left.reason) == (right.status, right.reason)
        for row, point in enumerate(causal_grid):
            expected_available_at = point.to_pydatetime() + timedelta(
                seconds=3 if row >= cut else 0
            )
            assert baseline.snapshots[row].available_at == point.to_pydatetime()
            assert perturbed.snapshots[row].available_at == expected_available_at
        assert any(
            math.isfinite(float(baseline_expected[row][column]))
            and (
                math.isnan(float(changed_expected[row][column]))
                or float(baseline_expected[row][column]) != float(changed_expected[row][column])
            )
            for row in range(cut, len(causal_grid))
            for column in range(len(causal_frames))
        ), "the future perturbation must produce a changed suffix witness"

    # Reversing feed, target, and registration order changes output column
    # layout only.  Per-asset values and independently checked nodes stay fixed.
    reorder_frames = _minute_frames(320)
    ordered_assets = tuple(reorder_frames)
    reordered_assets = tuple(reversed(ordered_assets))
    feed_order = reordered_assets[2:] + reordered_assets[:2]
    for mode in ("native", "build"):
        baseline, _cohort, _feeds = _run_live(
            reorder_frames, mode=mode, target_order=ordered_assets
        )
        baseline_matrix = _snapshot_matrix(baseline, ordered_assets)
        reordered, _cohort, _feeds = _run_live(
            reorder_frames,
            mode=mode,
            target_order=reordered_assets,
            feed_order=feed_order,
            registration_order=tuple(reversed(feed_order)),
        )
        _validate_live(
            reordered,
            {asset: reorder_frames[asset] for asset in reordered_assets},
            label="reordered live " + mode,
        )
        reordered_matrix = _snapshot_matrix(reordered, reordered_assets)
        for row in range(len(baseline_matrix)):
            by_asset = dict(zip(reordered_assets, reordered_matrix[row]))
            _assert_exact_matrix_equal(
                [baseline_matrix[row]],
                [[by_asset[asset] for asset in ordered_assets]],
                label="asset-order invariance %s row %d" % (mode, row),
            )
            for asset in ordered_assets:
                left = baseline.snapshots[row].factors["alpha003"].values[asset]
                right = reordered.snapshots[row].factors["alpha003"].values[asset]
                assert (left.status, left.reason) == (right.status, right.reason)

    # Reconstruct the first 400 bars from immutable history events, then stream
    # the suffix.  Its live suffix must equal an all-live continuous run.
    warmup_frames = _minute_frames(640)
    warmup_assets = tuple(warmup_frames)
    history_cut = 400
    for mode in ("native", "build"):
        continuous, _cohort, _feeds = _run_live(warmup_frames, mode=mode)
        continuous_expected, _continuous_factor = _validate_live(
            continuous,
            warmup_frames,
            label="continuous live %s T640" % mode,
        )
        rebuilt, _cohort, _feeds = _run_live(
            warmup_frames,
            mode=mode,
            history_bars=history_cut,
        )
        rebuilt_expected, rebuilt_factor = _validate_live(
            rebuilt,
            warmup_frames,
            label="history prewarm %s T640" % mode,
        )
        assert all(
            snapshot.readiness is LiveFactorReadiness.LIVE_READY
            for snapshot in rebuilt.snapshots[history_cut:]
        )
        _assert_exact_matrix_equal(
            _snapshot_matrix(continuous, warmup_assets)[history_cut:],
            _snapshot_matrix(rebuilt, warmup_assets)[history_cut:],
            label="history reconstruction suffix " + mode,
        )
        continuous_factor = continuous.live_factor_set.factor_instances["alpha003"]["default"]
        report = compare_factor_graphs(
            _factor_trace_view(
                continuous_factor,
                continuous,
                tuple(next(iter(warmup_frames.values())).index),
                label="continuous history graph %s" % mode,
            ),
            _factor_trace_view(
                rebuilt_factor,
                rebuilt,
                tuple(next(iter(warmup_frames.values())).index),
                label="rebuilt history graph %s" % mode,
            ),
            3,
        )
        assert report["equal"], "history graph/reason parity %s: %r" % (
            mode,
            report["failures"][:20],
        )
        assert_matrix_matches(
            _snapshot_matrix(rebuilt, warmup_assets)[history_cut:],
            rebuilt_expected[history_cut:],
            label="history independent suffix " + mode,
        )
        assert_matrix_matches(
            _snapshot_matrix(continuous, warmup_assets)[history_cut:],
            continuous_expected[history_cut:],
            label="continuous independent suffix " + mode,
        )
