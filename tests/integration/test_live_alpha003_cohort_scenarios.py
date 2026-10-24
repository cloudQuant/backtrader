"""Real Alpha003 cohort regressions for delayed and missing-member slots.

The live graph, feed delivery, and Cerebro scheduler are production objects.
Only immutable source events and the replay clock are synthetic.  Expected
values come from the independent Alpha101 paper-formula reference, with real
cohort presence supplied as its explicit formula-universe mask.
"""

from __future__ import annotations

import math
from datetime import timedelta
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import operators
from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import LiveBarCohort
from tests.integration import test_live_alpha003_parity as parity
from tests.test_utils.alpha101_full_reference import _Context, _parse, reference
from tests.test_utils.alpha101_native_harness import oracle_frames
from tests.test_utils.alpha101_trace_validation import (
    _compare_matrices,
    _exact_discrete_ast,
    _fold_constants,
    _postorder,
    _production_graph,
)


_FIELDS = parity._OHLCV_FIELDS
_ROWS = 320
_GAP_INDEX = 140
_DELAY_INDEX = _GAP_INDEX + 12
_DELAY_SECONDS = 2.0


class _CohortCapture(parity._LiveAlpha003Capture):
    """Keep test-side evidence that every callback followed a whole batch."""

    params = (("clock", None),)

    def __init__(self):
        super().__init__()
        self.line_lengths = []
        self.batch_member_counts = []
        self.batches = []
        self.callback_clock_times = []

    def _capture(self):
        super()._capture()
        batch = self.p.cohort.current_batch()
        self.line_lengths.append(tuple(len(data) for data in self.datas))
        self.batch_member_counts.append(len(batch.members))
        self.batches.append(batch)
        self.callback_clock_times.append(self.p.clock.utc_now())


def _scenario_frames(member_count):
    """Build three or twenty positive fixture members with varied rank paths."""
    source = parity._minute_frames(_ROWS)
    source_names = tuple(source)
    names = tuple("member-%02d" % index for index in range(member_count))
    frames = {}
    for index, name in enumerate(names):
        frame = source[source_names[index % len(source_names)]].copy(deep=True)
        if index >= len(source_names):
            # Deterministic small positive transforms create distinct, moving
            # cross-sectional ranks while retaining the source fixture's
            # finite time-series structure.
            open_values = []
            volume_values = []
            for row, (open_value, volume_value) in enumerate(zip(frame["open"], frame["volume"])):
                open_scale = 1.0 + 0.013 * index
                volume_scale = 1.0 + 0.009 * ((index * 7) % member_count)
                open_wave = 1.0 + 0.035 * math.sin(row * (0.019 + index * 0.00017) + index)
                volume_wave = 1.0 + 0.04 * math.cos(row * (0.023 + index * 0.00013) + index * 0.7)
                open_values.append(float(open_value) * open_scale * open_wave)
                volume_values.append(float(volume_value) * volume_scale * volume_wave)
            frame["open"] = open_values
            frame["volume"] = volume_values
            frame["high"] = [
                max(float(open_value), float(close_value)) + 0.5
                for open_value, close_value in zip(frame["open"], frame["close"])
            ]
            frame["low"] = [
                min(float(open_value), float(close_value)) - 0.5
                for open_value, close_value in zip(frame["open"], frame["close"])
            ]
        frames[name] = frame
    return frames


def _scenario_inputs(frames, *, gap_asset, gap_index, delayed_asset, delay_index):
    """Bind source values and explicit real-event presence into immutable bars."""
    events = {}
    oracle_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    oracle_frames[gap_asset].iloc[
        gap_index, oracle_frames[gap_asset].columns.get_loc("close")
    ] = math.nan
    for asset, frame in oracle_frames.items():
        rows = []
        for row_index, event in enumerate(parity._bar_events({asset: frame}, asset)):
            payload = dict(event)
            if asset == gap_asset and row_index == gap_index:
                payload.update(
                    {
                        "close": math.nan,
                        "present": False,
                        "quality": "MISSING",
                        "quality_flags": ("MISSING_FIELDS",),
                        "missing_fields": ("close",),
                    }
                )
            if asset == delayed_asset and row_index == delay_index:
                payload["available_at"] = payload["bucket_end"] + timedelta(seconds=_DELAY_SECONDS)
            rows.append(MappingProxyType(payload))
        events[asset] = tuple(rows)
    return oracle_frames, events


def _run_scenario(frames, *, mode, gap_index, delay_index):
    targets = tuple(frames)
    gap_asset = targets[-1]
    delayed_asset = targets[0]
    oracle_input, events = _scenario_inputs(
        frames,
        gap_asset=gap_asset,
        gap_index=gap_index,
        delayed_asset=delayed_asset,
        delay_index=delay_index,
    )
    grid = tuple(next(iter(oracle_input.values())).index)
    calendar, member_ids = parity._calendar(targets, grid)
    cohort = LiveBarCohort(
        "alpha003-cohort-scenario-%d-%s" % (len(targets), mode),
        calendar,
        max_pending_slots=2,
        max_window_bars=len(grid),
        wait_timeout_ns=5_000_000_000,
    )
    clock = parity._ReplayClock(grid[0].to_pydatetime())
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=0,
        preload=False,
        runonce=False,
    )
    feeds = {}
    feed_order = tuple(reversed(targets))
    for asset in feed_order:
        feed = bt.feeds.BtApiFeed(
            dataname=asset,
            historical_bars=(),
            live_bars=events[asset],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)

    for asset in reversed(targets):
        cohort.register_member(
            member_ids[asset],
            feeds[asset],
            instrument=asset,
            source_ref="feed-%s" % asset,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )

    plan = parity._live_alpha003_plan(
        targets,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=len(grid),
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=5.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _CohortCapture,
        cohort=cohort,
        plan=plan,
        target_order=targets,
        clock=clock,
    )
    strategy = cerebro.run()[0]

    assert len(strategy.snapshots) == len(grid)
    assert len(strategy.factor_callback_times) == len(grid)
    assert len(strategy.callback_clock_times) == len(grid)
    assert strategy.factor_callback_times == [point.to_pydatetime() for point in grid]
    assert strategy.line_lengths == [tuple([row + 1] * len(targets)) for row in range(len(grid))]
    assert strategy.batch_member_counts == [len(targets)] * len(grid)
    assert all(
        snapshot.close_time == point.to_pydatetime()
        for snapshot, point in zip(strategy.snapshots, grid)
    )

    for row_index, (batch, point) in enumerate(zip(strategy.batches, grid)):
        assert batch.status == "COMPLETE" and batch.close_time == point.to_pydatetime()
        assert len(batch.members) == len(targets)
        for asset, feed in feeds.items():
            receipt = batch.receipt_for_feed(feed)
            assert receipt.close_time == point.to_pydatetime(), (asset, row_index)
            assert receipt.slot_index == row_index, (asset, row_index)
            assert receipt.source_role == "live", (asset, row_index)
            assert receipt.complete is True, (asset, row_index)
            is_gap = asset == gap_asset and row_index == gap_index
            assert receipt.present is (not is_gap), (asset, row_index)
            assert receipt.quality == ("MISSING" if is_gap else "GOOD"), (asset, row_index)

    gap_feed = feeds[gap_asset]
    assert math.isfinite(float(gap_feed.open.array[gap_index]))
    assert math.isfinite(float(gap_feed.volume.array[gap_index]))
    assert math.isnan(float(gap_feed.close.array[gap_index]))
    delayed_time = grid[delay_index].to_pydatetime()
    delayed_snapshot = strategy.snapshots[delay_index]
    assert delayed_snapshot.close_time == delayed_time
    assert delayed_snapshot.available_at == delayed_time + timedelta(seconds=_DELAY_SECONDS)
    assert strategy.callback_clock_times[delay_index] >= delayed_snapshot.available_at
    assert clock.now >= delayed_snapshot.available_at and clock.waits

    return strategy, cohort, feeds, oracle_input, grid, gap_asset


def _line_array(line, rows):
    values = tuple(float(value) for value in line.array)
    assert len(values) == rows
    return values


def _node_values_and_reasons(factor, assets, rows):
    expected_keys = {"rank_open", "rank_volume"}
    expected_keys.update("correlation10_%d" % index for index in range(len(assets)))
    expected_keys.update("negate_%d" % index for index in range(len(assets)))
    assert set(factor._nodes) == expected_keys
    assert len(factor._nodes) == 2 + 2 * len(assets)

    values = {}
    reasons = {}
    for name in ("rank_open", "rank_volume"):
        node = factor._nodes[name]
        assert isinstance(node, operators.CrossSectionalRank)
        values[name] = tuple(
            _line_array(node.outputs[target].value, rows) for target in factor.target_datas
        )
        reasons[name] = tuple(
            tuple(int(value) for value in _line_array(node.outputs[target].reason, rows))
            for target in factor.target_datas
        )
    for index in range(len(assets)):
        for key in ("correlation10_%d" % index, "negate_%d" % index):
            node = factor._nodes[key]
            values[key] = _line_array(node.lines.value, rows)
            reasons[key] = tuple(int(value) for value in _line_array(node.lines.reason, rows))
    return values, reasons


def _validate_masked_graph(strategy, frames, *, gap_asset, gap_index, label):
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    factor = parity._factor_for_live(strategy)
    trace_factor = parity._factor_trace_view(factor, strategy, grid, label=label)
    matrices = oracle_frames(frames, grid=grid)
    mask = [[True] * len(assets) for _ in grid]
    gap_column = assets.index(gap_asset)
    mask[gap_index][gap_column] = False

    # This independent reference applies event membership inside its rank
    # evaluator. The source row remains present in the fixture so its finite
    # open/volume evidence is preserved while the real BarEvent marks the
    # member unavailable for that slot.
    expected_final = reference(3, matrices, formula_universe=mask)
    expected_root, production = _production_graph(trace_factor, 3)
    context = _Context(matrices, formula_universe=mask, snap_correlation_bounds=False)
    assert expected_root == _fold_constants(_parse(3))

    matched_ast_operators = 0
    for expression in _postorder(expected_root):
        candidates = production.get(expression, ())
        if not candidates:
            continue
        if expression[0] in ("call", "binary", "unary", "ternary"):
            matched_ast_operators += 1
        expected_values = context.evaluate(expression)
        for candidate_index, actual in enumerate(candidates):
            matched, message = _compare_matrices(
                actual,
                expected_values,
                exact=_exact_discrete_ast(expression),
                label="%s AST %r copy %d" % (label, expression, candidate_index),
            )
            assert matched, message
    assert matched_ast_operators == 4
    expected_from_tree = context.evaluate(expected_root)
    matched, message = _compare_matrices(
        expected_from_tree, expected_final, exact=False, label=label + " final oracle projection"
    )
    assert matched, message

    actual_snapshot = parity._snapshot_matrix(strategy, assets)
    matched, message = _compare_matrices(
        actual_snapshot, expected_final, exact=False, label=label + " live result"
    )
    assert matched, message

    values, reasons = _node_values_and_reasons(factor, assets, len(grid))
    from backtrader.research.operators import OperatorReason

    rank_open = context.evaluate(
        next(
            expression
            for expression in production
            if expression[0] == "call"
            and expression[1] == "rank"
            and expression[2][0] == ("name", "open")
        )
    )
    rank_volume = context.evaluate(
        next(
            expression
            for expression in production
            if expression[0] == "call"
            and expression[1] == "rank"
            and expression[2][0] == ("name", "volume")
        )
    )
    for name, oracle in (("rank_open", rank_open), ("rank_volume", rank_volume)):
        for asset_index, asset in enumerate(assets):
            matched, message = _compare_matrices(
                [[item] for item in values[name][asset_index]],
                [[row[asset_index]] for row in oracle],
                exact=True,
                label="%s %s %s" % (label, name, asset),
            )
            assert matched, message
            expected_rank_reason = (
                OperatorReason.FORMULA_INELIGIBLE if asset == gap_asset else OperatorReason.READY
            )
            actual_reasons = reasons[name][asset_index]
            for row_index, reason in enumerate(actual_reasons):
                expected_reason = (
                    expected_rank_reason if row_index == gap_index else OperatorReason.READY
                )
                assert reason == int(expected_reason), (label, name, asset, row_index, reason)

    correlation_ast = next(
        expression
        for expression in production
        if expression[0] == "call" and expression[1] == "correlation"
    )
    correlation_expected = context.evaluate(correlation_ast)
    for asset_index, asset in enumerate(assets):
        for prefix, value_key in (
            ("correlation10", "correlation10_%d" % asset_index),
            ("negate", "negate_%d" % asset_index),
        ):
            actual = values[value_key]
            actual_reasons = reasons[value_key]
            for row_index, value in enumerate(actual):
                wanted = float(correlation_expected[row_index][asset_index])
                if prefix == "negate" and math.isfinite(wanted):
                    wanted = -wanted
                if math.isnan(wanted):
                    assert math.isnan(value), (label, prefix, asset, row_index, value)
                else:
                    assert value == pytest.approx(wanted, rel=1e-10, abs=1e-12), (
                        label,
                        prefix,
                        asset,
                        row_index,
                    )
                if row_index < 9:
                    expected_reason = OperatorReason.NOT_READY
                elif asset == gap_asset and gap_index <= row_index <= gap_index + 9:
                    expected_reason = OperatorReason.INCOMPLETE_WINDOW
                elif math.isfinite(float(correlation_expected[row_index][asset_index])):
                    expected_reason = OperatorReason.READY
                else:
                    expected_reason = OperatorReason.DOMAIN_ERROR
                assert actual_reasons[row_index] == int(expected_reason), (
                    label,
                    prefix,
                    asset,
                    row_index,
                    actual_reasons[row_index],
                    expected_reason.name,
                )

    gap_output = strategy.snapshots[gap_index].factors["alpha003"].values[gap_asset]
    assert gap_output.present is False and gap_output.quality == "MISSING"
    assert gap_output.status.value == "OUTPUT_UNAVAILABLE" and math.isnan(gap_output.value)
    assert strategy.snapshots[gap_index].readiness is LiveFactorReadiness.WARMUP
    assert "cohort_gap_present" in strategy.snapshots[gap_index].readiness_reasons

    incomplete = strategy.snapshots[gap_index + 9]
    assert incomplete.readiness is LiveFactorReadiness.WARMUP
    assert "input_window_incomplete_or_warmup_short" in incomplete.readiness_reasons
    incomplete_output = incomplete.factors["alpha003"].values[gap_asset]
    assert incomplete_output.present is True
    assert incomplete_output.status.value == "OUTPUT_UNAVAILABLE"
    assert incomplete_output.reason == "INCOMPLETE_WINDOW"
    assert math.isnan(incomplete_output.value)

    recovered = strategy.snapshots[gap_index + 10]
    recovered_output = recovered.factors["alpha003"].values[gap_asset]
    assert recovered_output.status.value == "OUTPUT_AVAILABLE"
    assert recovered_output.reason is None and math.isfinite(recovered_output.value)
    # The formula's ten-bar rolling output recovers here. The declared live
    # plan still requires thirty complete bars before overall LIVE_READY.
    assert recovered.readiness is LiveFactorReadiness.WARMUP
    assert "input_window_incomplete_or_warmup_short" in recovered.readiness_reasons
    live_ready = strategy.snapshots[gap_index + 30]
    assert live_ready.readiness is LiveFactorReadiness.LIVE_READY
    assert "input_window_incomplete_or_warmup_short" not in live_ready.readiness_reasons
    recovery_witnesses = sum(
        math.isfinite(float(value)) for row in actual_snapshot[gap_index + 10 :] for value in row
    )
    assert recovery_witnesses >= 100, (label, recovery_witnesses)
    assert "rank_open" in values and "rank_volume" in values
    return factor, values, reasons, actual_snapshot


@pytest.mark.integration
@pytest.mark.parametrize("member_count", (3, 20))
@pytest.mark.parametrize("mode", ("native", "build"))
def test_alpha003_live_cohort_delayed_gap_membership_and_window_recovery(member_count, mode):
    """Check delay barrier, exact gap masking, sealed prefix and recovery."""
    base_frames = _scenario_frames(member_count)
    assets = tuple(base_frames)
    gap_index = _GAP_INDEX
    delay_index = _DELAY_INDEX

    baseline, _baseline_cohort, _baseline_feeds = parity._run_live(base_frames, mode=mode)
    baseline_expected, baseline_factor = parity._validate_live(
        baseline, base_frames, label="%d members %s no-gap baseline" % (member_count, mode)
    )
    assert len(baseline_expected) == _ROWS
    assert len(baseline.snapshots) == _ROWS

    scenario, cohort, feeds, oracle_frames, grid, gap_asset = _run_scenario(
        base_frames,
        mode=mode,
        gap_index=gap_index,
        delay_index=delay_index,
    )
    label = "%d members %s delayed cohort gap" % (member_count, mode)
    factor, node_values, node_reasons, actual = _validate_masked_graph(
        scenario,
        oracle_frames,
        gap_asset=gap_asset,
        gap_index=gap_index,
        label=label,
    )

    # The not-yet-observed suffix cannot revise the already sealed prefix.
    baseline_values = parity._snapshot_matrix(baseline, assets)
    assert len(baseline_values[:gap_index]) == gap_index
    assert len(actual[:gap_index]) == gap_index
    matched, message = _compare_matrices(
        actual[:gap_index],
        baseline_values[:gap_index],
        exact=True,
        label=label + " sealed snapshot prefix",
    )
    assert matched, message
    for row in range(gap_index):
        for column, asset in enumerate(assets):
            left = baseline.snapshots[row].factors["alpha003"].values[asset]
            right = scenario.snapshots[row].factors["alpha003"].values[asset]
            assert (left.status, left.reason, left.present, left.quality) == (
                right.status,
                right.reason,
                right.present,
                right.quality,
            ), (label, row, asset)

    baseline_trace = parity._factor_trace_view(
        baseline_factor, baseline, grid, label=label + " baseline trace"
    )
    scenario_trace = parity._factor_trace_view(
        factor, scenario, grid, label=label + " scenario trace"
    )
    baseline_nodes, baseline_reasons = _node_values_and_reasons(baseline_trace, assets, _ROWS)
    scenario_nodes, scenario_reasons = _node_values_and_reasons(scenario_trace, assets, _ROWS)
    for key in baseline_nodes:
        left_value = baseline_nodes[key]
        right_value = scenario_nodes[key]
        left_reason = baseline_reasons[key]
        right_reason = scenario_reasons[key]
        if key.startswith("rank_"):
            for column, asset in enumerate(assets):
                matched, message = _compare_matrices(
                    [[value] for value in left_value[column][:gap_index]],
                    [[value] for value in right_value[column][:gap_index]],
                    exact=True,
                    label="%s %s %s sealed rank prefix" % (label, key, asset),
                )
                assert matched, message
                assert left_reason[column][:gap_index] == right_reason[column][:gap_index], (
                    label,
                    key,
                    asset,
                )
        else:
            matched, message = _compare_matrices(
                [[value] for value in left_value[:gap_index]],
                [[value] for value in right_value[:gap_index]],
                exact=True,
                label="%s %s sealed scalar prefix" % (label, key),
            )
            assert matched, message
            assert left_reason[:gap_index] == right_reason[:gap_index], (label, key)

    assert cohort.current_batch().status == "COMPLETE"
    assert len(cohort.current_batch().members) == member_count
    assert len(feeds) == member_count
    assert all(feed.live_bar_cohort is cohort for feed in feeds.values())
    assert scenario.snapshots[delay_index].available_at == (
        grid[delay_index].to_pydatetime() + timedelta(seconds=_DELAY_SECONDS)
    )
    assert node_values["rank_open"] and node_values["rank_volume"]
    assert node_reasons["rank_open"] and node_reasons["rank_volume"]
