"""Logical grid indexing contracts for research operators over qbuffers."""

import hashlib
import math
import struct
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
import backtrader.research.operators as operators
from backtrader.linebuffer import LineBuffer
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research import align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.research.operators import OperatorReason
from backtrader.research.specs import ResearchSpec
from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_native_harness import (
    make_positive_fixture,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import validate_factor_trace


def _queued_line(values, capacity):
    line = LineBuffer()
    line._minperiod = capacity
    line.qbuffer()
    for value in values:
        line.forward()
        line[0] = value
    return line


def _panel_target(capacity, rows):
    clock = _queued_line(range(rows), capacity)
    return SimpleNamespace(lines=SimpleNamespace(lines=[clock]))


def test_panel_value_and_reason_use_each_qbuffers_logical_origin():
    rows = 12
    target = _panel_target(capacity=1, rows=rows)
    values = _queued_line([float(index) + 0.25 for index in range(rows)], capacity=4)
    reasons = _queued_line([int(OperatorReason.READY)] * rows, capacity=2)
    values._factor_research_target = target
    values._factor_research_reason_line = reasons

    value, reason = operators._read_panel_value(values, target)

    assert (value, reason) == (11.25, OperatorReason.READY)
    evicted, evicted_reason = operators._read_panel_value_at(values, target, 7)
    assert math.isnan(evicted)
    assert evicted_reason is OperatorReason.NOT_READY


def test_panel_nan_reason_is_read_from_its_own_qbuffer_slot():
    rows = 12
    target = _panel_target(capacity=1, rows=rows)
    source_values = [float(index) for index in range(rows)]
    source_values[-1] = float("nan")
    reasons = [int(OperatorReason.READY)] * rows
    reasons[-1] = int(OperatorReason.DOMAIN_ERROR)
    values = _queued_line(source_values, capacity=4)
    reason_line = _queued_line(reasons, capacity=2)
    values._factor_research_target = target
    values._factor_research_reason_line = reason_line

    value, reason = operators._read_panel_value(values, target)

    assert math.isnan(value)
    assert reason is OperatorReason.DOMAIN_ERROR


def test_scalar_qbuffer_nan_reason_uses_the_source_logical_row():
    rows = 12
    source_values = [float(index) for index in range(rows)]
    source_values[-1] = float("nan")
    reason_values = [int(OperatorReason.READY)] * rows
    reason_values[-1] = int(OperatorReason.UNKNOWN_CLASSIFICATION)
    source = _queued_line(source_values, capacity=4)
    reason_line = _queued_line(reason_values, capacity=2)
    source._factor_research_reason_line = reason_line

    value, reason = operators._read_value(source)

    assert math.isnan(value)
    assert reason is OperatorReason.UNKNOWN_CLASSIFICATION


def test_scalar_qbuffer_reads_retained_relative_rows_and_rejects_evicted_rows():
    source = _queued_line([float(index) for index in range(12)], capacity=4)

    assert operators._read_value(source, ago=-2) == (9.0, OperatorReason.READY)
    value, reason = operators._read_value(source, ago=-5)

    assert math.isnan(value)
    assert reason is OperatorReason.NOT_READY


def test_unbounded_reason_rejects_negative_absolute_index():
    source = LineBuffer()
    reason_line = LineBuffer()
    reason_line.forward()
    reason_line[0] = int(OperatorReason.DOMAIN_ERROR)
    source._factor_research_reason_line = reason_line

    assert operators._associated_reason(source, absolute_index=-1) is None


def test_panel_window_uses_global_grid_and_reports_evicted_history_as_not_ready():
    rows = 12
    target = _panel_target(capacity=1, rows=rows)
    values = _queued_line([float(index) for index in range(rows)], capacity=4)
    values._factor_research_target = target

    window, reason = operators._read_panel_window(values, target, period=3)
    unavailable, unavailable_reason = operators._read_panel_window(values, target, period=5)

    assert (window, reason) == ([9.0, 10.0, 11.0], OperatorReason.READY)
    assert unavailable is None
    assert unavailable_reason is OperatorReason.NOT_READY


def _alpha003_frames(rows=1280, assets=5):
    index = pd.date_range("2025-01-01", periods=rows, freq="D", tz="UTC")
    frames = {}
    for asset in range(assets):
        opens = []
        volumes = []
        for row in range(rows):
            opens.append(
                100.0
                + asset * 2.0
                + 8.0 * math.sin(row * 0.17 + asset * 1.3)
                + ((row * asset) % 5) * 0.3
            )
            volumes.append(
                10000.0
                + ((row * (asset + 2) + asset * 7) % 19) * 137.0
                + asset * 29.0
            )
        frames["asset-%d" % asset] = pd.DataFrame(
            {
                "open": opens,
                "high": [value + 1.0 for value in opens],
                "low": [value - 1.0 for value in opens],
                "close": list(opens),
                "volume": volumes,
                "openinterest": [0.0] * rows,
            },
            index=index,
        )
    return index, frames


def _run_alpha003_exactbars(frames, exactbars):
    index = next(iter(frames.values())).index
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=6)},
        index=index.rename("close_time"),
    )
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=tuple(frames),
        source_timezone="UTC",
        snapshot_id="iteration50-alpha003-qbuffer-grid-v1",
        price_basis="synthetic deterministic OHLC and volume units",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        feed_time_kind="close_time",
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, exactbars=exactbars)

    for asset, frame in frames.items():
        aligned = align_to_grid(frame, research, asset)
        cerebro.adddata(aligned.feed, name=asset)

    class _CaptureAlpha003(bt.Strategy):
        def __init__(self):
            self.alpha = get_alpha(3).bind(*self.datas)
            self.rows = []

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

        def next(self):
            self.rows.append(
                tuple(float(self.alpha.outputs[data].factor[0]) for data in self.datas)
            )

    cerebro.addstrategy(_CaptureAlpha003)
    return cerebro.run()[0]


def _max_qbuffer_capacity(strategy):
    capacities = []
    pending = [strategy, *strategy.datas]
    visited = set()
    while pending:
        owner = pending.pop()
        if id(owner) in visited:
            continue
        visited.add(id(owner))
        lines = getattr(getattr(owner, "lines", None), "lines", ())
        capacities.extend(
            line.maxlen for line in lines if line.mode == LineBuffer.QBuffer
        )
        for children in getattr(owner, "_lineiterators", {}).values():
            pending.extend(children)
    return max(capacities, default=0)


def test_alpha003_matches_full_buffers_after_ten_qbuffer_wraps():
    index, frames = _alpha003_frames()

    full = _run_alpha003_exactbars(frames, exactbars=0)
    queued = _run_alpha003_exactbars(frames, exactbars=1)

    as_bits = lambda value: struct.pack("=d", value)
    max_capacity = _max_qbuffer_capacity(queued)
    assert max_capacity >= 10  # Rolling correlation must retain its full window.
    assert len(index) >= max(1280, 10 * max_capacity)
    assert len(full.rows) == len(queued.rows) == len(index)
    finite_values = [value for row in full.rows for value in row if math.isfinite(value)]
    assert len(finite_values) >= len(index)
    assert len({as_bits(value) for value in finite_values}) > 1
    assert [[as_bits(value) for value in row] for row in queued.rows] == [
        [as_bits(value) for value in row] for row in full.rows
    ]


def _alpha101_long_gap_fixture(rows=4096):
    """Reuse the accepted positive six-asset fixture with real gaps and NaNs."""
    frames = {asset: frame.copy() for asset, frame in make_positive_fixture(rows).items()}
    grid = tuple(next(iter(frames.values())).index)
    frames["asset-1"] = frames["asset-1"].drop(index=grid[rows // 2])
    frames["asset-3"].loc[grid[rows // 4], "high"] = math.nan
    frames["asset-4"].loc[grid[-4], "close"] = math.nan
    return frames


def _float_token(value):
    value = float(value)
    if math.isnan(value):
        return b"N;"
    if math.isinf(value):
        raise AssertionError("factor graph contains infinity")
    return (value.hex() + ";").encode("ascii")


def _reason_token(value):
    value = float(value)
    if math.isnan(value):
        # Some long-window panel nodes are deliberately uninitialized before
        # their first eligible callback. Their value and reason NaN prefixes
        # must still match exactly between the two buffer profiles.
        return b"N;"
    if not math.isfinite(value) or value != int(value):
        raise AssertionError("factor graph reason is not a finite integer code")
    try:
        OperatorReason(int(value))
    except ValueError as exc:
        raise AssertionError("factor graph contains an unknown reason code") from exc
    return (str(int(value)) + ";").encode("ascii")


def _node_line_pairs(node):
    """Yield all value/reason outputs belonging to one registered graph node."""
    if isinstance(node, operators._PanelOperator):
        for data in node._factor_target_datas:
            output = node.outputs[data]
            yield str(getattr(data, "_name", "")), output.value, output.reason
        return

    lines = getattr(node, "lines", None)
    value = getattr(lines, "value", None)
    reason = getattr(lines, "reason", None)
    if value is None:
        raise AssertionError("registered factor node has no value line")
    if reason is None:
        reason = getattr(value, "_factor_research_reason_line", None)
    if reason is None:
        raise AssertionError("registered factor node has no reason line")
    target = getattr(node, "_target_data", None)
    yield str(getattr(target, "_name", "")), value, reason


def _capture_factor_node_row(strategy, streams, *, retain_tokens=False):
    """Observe the already-scheduled factor nodes at the current strategy row."""
    for factor_name, instances in strategy._factor_instances_by_name.items():
        for group_index, factor in enumerate(instances):
            seen = set()
            entries = list(factor._nodes.items())
            entries.extend(
                ("@physical:%d" % index, node)
                for index, node in enumerate(getattr(factor, "_physical_nodes", ()))
            )
            for node_key, node in entries:
                identity = id(node)
                if identity in seen and str(node_key).startswith("@physical:"):
                    continue
                seen.add(identity)
                for output_name, value_line, reason_line in _node_line_pairs(node):
                    stream_key = (
                        factor_name,
                        group_index,
                        str(node_key),
                        type(node).__module__,
                        type(node).__qualname__,
                        output_name,
                    )
                    state = streams.setdefault(
                        stream_key,
                        {
                            "values": hashlib.sha256(),
                            "reasons": hashlib.sha256(),
                            "value_cells": 0,
                            "reason_cells": 0,
                            "reason_codes": 0,
                        },
                    )
                    value_token = _float_token(value_line[0])
                    state["values"].update(value_token)
                    raw_reason = float(reason_line[0])
                    reason_token = _reason_token(raw_reason)
                    state["reasons"].update(reason_token)
                    if retain_tokens:
                        state.setdefault("value_tokens", []).append(value_token)
                        state.setdefault("reason_tokens", []).append(reason_token)
                    state["value_cells"] += 1
                    state["reason_cells"] += 1
                    state["reason_codes"] += math.isfinite(raw_reason)


def _stream_summary(streams):
    return {
        key: {
            "values": state["values"].hexdigest(),
            "reasons": state["reasons"].hexdigest(),
            "value_cells": state["value_cells"],
            "reason_cells": state["reason_cells"],
            "reason_codes": state["reason_codes"],
            **(
                {
                    "value_tokens": tuple(state["value_tokens"]),
                    "reason_tokens": tuple(state["reason_tokens"]),
                }
                if "value_tokens" in state
                else {}
            ),
        }
        for key, state in streams.items()
    }


def _first_stream_difference(left, right):
    for key in sorted(set(left) | set(right), key=repr):
        left_state, right_state = left.get(key), right.get(key)
        if left_state is None or right_state is None:
            return "%r stream presence differs" % (key,)
        for field in ("value_tokens", "reason_tokens"):
            left_tokens = left_state.get(field)
            right_tokens = right_state.get(field)
            if left_tokens is None or right_tokens is None:
                continue
            if len(left_tokens) != len(right_tokens):
                return "%r %s row count %d != %d" % (
                    key, field, len(left_tokens), len(right_tokens)
                )
            for row_index, (left_token, right_token) in enumerate(zip(left_tokens, right_tokens)):
                if left_token != right_token:
                    return "%r %s row %d: %r != %r" % (
                        key, field, row_index, left_token, right_token
                    )
    return None


def _run_alpha101_buffer_batch(
    monkeypatch,
    frames,
    alpha_ids,
    *,
    mode,
    exactbars,
    retain_tokens=False,
):
    """Run the existing FactorStrategy harness with one test-only row observer."""
    original_cerebro = bt.Cerebro
    original_collect = FactorStrategy._collect_current_grid_point
    streams = {}
    rows_seen = 0

    def configured_cerebro(*args, **kwargs):
        kwargs["exactbars"] = exactbars
        return original_cerebro(*args, **kwargs)

    def observed_collect(strategy):
        nonlocal rows_seen
        original_collect(strategy)
        rows_seen += 1
        # This runs from FactorStrategy's ordinary prenext/next callbacks. It
        # observes outputs after Cerebro scheduled their calculation; it does
        # not advance factors or introduce another time loop.
        _capture_factor_node_row(strategy, streams, retain_tokens=retain_tokens)

    with monkeypatch.context() as patch:
        patch.setattr(bt, "Cerebro", configured_cerebro)
        patch.setattr(FactorStrategy, "_collect_current_grid_point", observed_collect)
        strategy = run_native_batch(
            frames,
            alpha_ids,
            runonce=False,
            factor_mode=mode,
        )

    if rows_seen != len(next(iter(frames.values())).index):
        raise AssertionError("normal FactorStrategy callback did not observe every grid row")
    return strategy, _stream_summary(streams)


def _qbuffer_profile(strategy):
    """Return configured and actually retained qbuffer capacities in the run."""
    pending = [strategy, *strategy.datas]
    pending.extend(
        factor
        for instances in strategy._factor_instances_by_name.values()
        for factor in instances
    )
    visited = set()
    configured = []
    retained = []
    while pending:
        owner = pending.pop()
        if id(owner) in visited:
            continue
        visited.add(id(owner))
        lines = getattr(getattr(owner, "lines", None), "lines", ())
        for line in lines:
            if getattr(line, "mode", None) != LineBuffer.QBuffer:
                continue
            configured.append(int(line.maxlen))
            retained.append(len(line.array) - int(line.extension))
        for children in getattr(owner, "_lineiterators", {}).values():
            pending.extend(children)
    return tuple(configured), tuple(retained)


def _assert_exact_matrices(left, right, *, label):
    if len(left) != len(right):
        raise AssertionError("%s row count differs" % label)
    for row_index, (left_row, right_row) in enumerate(zip(left, right)):
        if len(left_row) != len(right_row):
            raise AssertionError("%s asset count differs at row %d" % (label, row_index))
        for asset_index, (left_value, right_value) in enumerate(zip(left_row, right_row)):
            left_value, right_value = float(left_value), float(right_value)
            if math.isnan(left_value) or math.isnan(right_value):
                if not (math.isnan(left_value) and math.isnan(right_value)):
                    raise AssertionError(
                        "%s NaN mask differs at row %d asset %d"
                        % (label, row_index, asset_index)
                    )
            elif math.isinf(left_value) or math.isinf(right_value) or left_value != right_value:
                raise AssertionError(
                    "%s differs at row %d asset %d: %.17g != %.17g"
                    % (label, row_index, asset_index, left_value, right_value)
                )


def _panel_factor_matrix(strategy, alpha_id, grid, assets):
    factors = strategy.get_panel().factors
    name = "alpha%d" % alpha_id
    values = factors[name].unstack(level="asset").reindex(index=grid, columns=assets)
    return values.to_numpy(dtype="float64").tolist()


def test_alpha101_prefix_uses_node_aware_scalar_trace_for_rank_outputs():
    """The accepted oracle compares each node before its values feed rank nodes."""
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    alpha_ids = tuple(formula_ids()[:20])
    patch = pytest.MonkeyPatch()
    try:
        full_strategy, full_streams = _run_alpha101_buffer_batch(
            patch, frames, alpha_ids, mode="native", exactbars=0, retain_tokens=True
        )
    finally:
        patch.undo()

    for alpha_id in alpha_ids:
        factor = full_strategy.factor_instances["alpha%d" % alpha_id]
        trace = validate_factor_trace(
            factor, alpha_id, frames, assets, grid, strategy=full_strategy
        )
        assert not trace["failures"], "Alpha%d node-aware trace failed: %r" % (
            alpha_id,
            trace["failures"][:8],
        )

    patch = pytest.MonkeyPatch()
    try:
        queued_strategy, queued_streams = _run_alpha101_buffer_batch(
            patch, frames, alpha_ids, mode="native", exactbars=1, retain_tokens=True
        )
    finally:
        patch.undo()
    assert set(full_streams) == set(queued_streams)
    stream_difference = _first_stream_difference(full_streams, queued_streams)
    assert stream_difference is None, stream_difference
    for alpha_id in alpha_ids:
        _assert_exact_matrices(
            _panel_factor_matrix(full_strategy, alpha_id, grid, assets),
            _panel_factor_matrix(queued_strategy, alpha_id, grid, assets),
            label="Alpha%d T320 full/qbuffer smoke" % alpha_id,
        )
    configured, retained = _qbuffer_profile(queued_strategy)
    assert configured and retained
    actual_max = max(retained)
    assert actual_max > 0
    print(
        "Alpha101 qbuffer prefix complete: mode=native formulas=%d-%d rows=%d "
        "actual_max_retained=%d complete_wraps=%d"
        % (alpha_ids[0], alpha_ids[-1], len(grid), actual_max, len(grid) // actual_max),
        flush=True,
    )


@pytest.mark.slow
def test_alpha101_full_and_qbuffer_native_build_values_and_reasons_match(monkeypatch):
    """Compare all 101 formulas over a long, gapped real Cerebro history."""
    rows = 3072
    frames = _alpha101_long_gap_fixture(rows)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    alpha_ids = tuple(formula_ids())
    batches = tuple(alpha_ids[offset : offset + 20] for offset in range(0, len(alpha_ids), 20))
    lane_capacity_receipts = {}
    for mode in ("native", "build"):
        for batch in batches:
            full_strategy, full_streams = _run_alpha101_buffer_batch(
                monkeypatch, frames, batch, mode=mode, exactbars=0
            )
            full_matrices = {}
            for alpha_id in batch:
                actual = _panel_factor_matrix(full_strategy, alpha_id, grid, assets)
                declared_h = history_h(alpha_id)
                finite = [
                    float(value)
                    for row in actual[declared_h:]
                    for value in row
                    if math.isfinite(float(value))
                ]
                assert finite, "Alpha%d %s full run has no finite post-H witness" % (
                    alpha_id,
                    mode,
                )
                assert any(value != 0.0 for value in finite), (
                    "Alpha%d %s full run has only zero post-H values" % (alpha_id, mode)
                )
                full_matrices[alpha_id] = actual

            queued_strategy, queued_streams = _run_alpha101_buffer_batch(
                monkeypatch, frames, batch, mode=mode, exactbars=1
            )
            configured, retained = _qbuffer_profile(queued_strategy)
            assert configured and retained, "exactbars=1 run produced no actual qbuffer lines"
            max_retained = max(retained)
            lane_capacity_receipts[(mode, batch[0], batch[-1])] = {
                "configured_maxlen": max(configured),
                "actual_retained_max": max_retained,
                "complete_wraps": rows // max_retained,
            }
            assert max_retained > 0
            assert rows >= max(1280, 10 * max_retained), (
                "Alpha101 %s/%d-%d fixture does not wrap its actual max retained capacity "
                "ten times: rows=%d actual_max=%d"
                % (mode, batch[0], batch[-1], rows, max_retained)
            )
            if full_streams.keys() != queued_streams.keys():
                missing = sorted(set(full_streams) ^ set(queued_streams), key=repr)
                raise AssertionError("%s node inventory changed with qbuffer: %r" % (mode, missing[:8]))
            for key in full_streams:
                if full_streams[key]["reason_codes"] == 0:
                    raise AssertionError("%s %s node has no numeric reason witness" % (mode, key))
                if full_streams[key] != queued_streams[key]:
                    raise AssertionError(
                        "%s %s qbuffer node values/reasons differ: %r != %r"
                        % (mode, key, full_streams[key], queued_streams[key])
                    )

            for alpha_id in batch:
                actual = _panel_factor_matrix(queued_strategy, alpha_id, grid, assets)
                declared_h = history_h(alpha_id)
                _assert_exact_matrices(
                    full_matrices[alpha_id],
                    actual,
                    label="Alpha%d %s full/qbuffer result" % (alpha_id, mode),
                )
                finite = [
                    float(value)
                    for row in actual[declared_h:]
                    for value in row
                    if math.isfinite(float(value))
                ]
                assert finite, "Alpha%d %s qbuffer run has no finite post-H witness" % (
                    alpha_id,
                    mode,
                )
                assert any(value != 0.0 for value in finite), (
                    "Alpha%d %s qbuffer run has only zero post-H values" % (alpha_id, mode)
                )

            print(
                "Alpha101 qbuffer lane complete: mode=%s formulas=%d-%d rows=%d "
                "configured_maxlen=%d actual_max_retained=%d complete_wraps=%d"
                % (
                    mode,
                    batch[0],
                    batch[-1],
                    rows,
                    max(configured),
                    max_retained,
                    rows // max_retained,
                ),
                flush=True,
            )

    assert len(lane_capacity_receipts) == len(batches) * 2
    assert all(receipt["actual_retained_max"] > 0 for receipt in lane_capacity_receipts.values())
    assert all(receipt["complete_wraps"] >= 10 for receipt in lane_capacity_receipts.values())
