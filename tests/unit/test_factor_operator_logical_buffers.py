"""Logical grid indexing contracts for research operators over qbuffers."""

import hashlib
import math
import struct
from collections import Counter
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
            volumes.append(10000.0 + ((row * (asset + 2) + asset * 7) % 19) * 137.0 + asset * 29.0)
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
        capacities.extend(line.maxlen for line in lines if line.mode == LineBuffer.QBuffer)
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
                    key,
                    field,
                    len(left_tokens),
                    len(right_tokens),
                )
            for row_index, (left_token, right_token) in enumerate(zip(left_tokens, right_tokens)):
                if left_token != right_token:
                    return "%r %s row %d: %r != %r" % (
                        key,
                        field,
                        row_index,
                        left_token,
                        right_token,
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
    capacity_observation=None,
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
        if capacity_observation is not None:
            _sample_qbuffer_capacity(strategy, capacity_observation)
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


def _qbuffer_inventory(strategy):
    """Collect exact QBuffer line identities by their existing graph roles."""
    roles = ("target", "input", "value", "reason")
    role_lines = {role: {} for role in roles}
    target_labels = {}
    direct_inputs, derived_inputs = set(), set()

    def add(role, line, label):
        identity = id(line)
        if identity in role_lines[role]:
            return
        if getattr(line, "mode", None) != LineBuffer.QBuffer:
            raise AssertionError("%s line %s is not an actual QBuffer" % (role, label))
        configured = int(line.maxlen)
        if configured <= 0:
            raise AssertionError("%s line %s has nonpositive maxlen %d" % (role, label, configured))
        role_lines[role][identity] = (line, label)

    for data in strategy.datas:
        aliases, lines = tuple(data.getlinealiases()), tuple(data.lines.lines)
        if len(aliases) != len(lines):
            raise AssertionError("target feed aliases do not match its buffers")
        for alias, line in zip(aliases, lines):
            label = "%s.%s" % (getattr(data, "_name", ""), alias)
            add("target", line, label)
            target_labels[id(line)] = label

    for name, instances in strategy._factor_instances_by_name.items():
        for group, factor in enumerate(instances):
            for alias, lines in factor._field_line_cache.items():
                for index, line in enumerate(lines):
                    identity = id(line)
                    source = target_labels.get(identity)
                    if source is None:
                        owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
                        source = type(owner).__name__
                        derived_inputs.add(identity)
                    else:
                        direct_inputs.add(identity)
                    add("input", line, "%s[%d].%s<-%s" % (name, group, alias, source))

    for name, instances in strategy._factor_instances_by_name.items():
        for group, factor in enumerate(instances):
            entries = list(factor._nodes.items()) + [
                ("@physical:%d" % i, node)
                for i, node in enumerate(getattr(factor, "_physical_nodes", ()))
            ]
            seen_nodes = set()
            for node_key, node in entries:
                if id(node) in seen_nodes:
                    continue
                seen_nodes.add(id(node))
                for target, value_line, reason_line in _node_line_pairs(node):
                    label = "%s[%d].%s.%s@%s" % (
                        name,
                        group,
                        node_key,
                        type(node).__name__,
                        target or "<unnamed>",
                    )
                    add("value", value_line, label)
                    add("reason", reason_line, label)

    if not direct_inputs or direct_inputs & derived_inputs:
        raise AssertionError("field inputs do not include exact target feed lines")
    return {
        "roles": role_lines,
        "direct_inputs": direct_inputs,
        "derived_inputs": derived_inputs,
    }


def _sample_qbuffer_capacity(strategy, observation):
    """Sample configured and retained capacities in the live strategy callback."""
    if not observation:
        inventory = _qbuffer_inventory(strategy)
        lines = {}
        for entries in inventory["roles"].values():
            for identity, (line, label) in entries.items():
                previous = lines.get(identity)
                if previous is not None and previous["line"] is not line:
                    raise AssertionError("line identity was reused during QBuffer inventory")
                lines.setdefault(
                    identity,
                    {
                        "line": line,
                        "label": label,
                        "configured": int(line.maxlen),
                        "retained_highwater": 0,
                        "samples": 0,
                    },
                )
        observation.update({"inventory": inventory, "lines": lines, "callbacks": 0})

    for state in observation["lines"].values():
        line = state["line"]
        if getattr(line, "mode", None) != LineBuffer.QBuffer:
            raise AssertionError("sampled line %s stopped being a QBuffer" % state["label"])
        configured = int(line.maxlen)
        retained = int(line.buflen())
        if configured != state["configured"]:
            raise AssertionError("QBuffer maxlen changed during the run for %s" % state["label"])
        if configured <= 0 or retained < 0 or retained > configured:
            raise AssertionError(
                "%s observed invalid QBuffer capacity %d/%d"
                % (state["label"], configured, retained)
            )
        state["retained_highwater"] = max(state["retained_highwater"], retained)
        state["samples"] += 1
    observation["callbacks"] += 1


def _qbuffer_profile(strategy, observation):
    """Summarize callback-sampled QBuffer high-water by exact line identity."""
    current = _qbuffer_inventory(strategy)
    sampled = observation["inventory"]
    assert observation["callbacks"] > 0
    for role in sampled["roles"]:
        previous_lines = sampled["roles"][role]
        current_lines = current["roles"][role]
        if previous_lines.keys() != current_lines.keys() or any(
            previous_lines[identity][0] is not current_lines[identity][0]
            for identity in previous_lines.keys() & current_lines.keys()
        ):
            raise AssertionError("QBuffer line identities changed after the sampled run")

    roles = tuple(sampled["roles"])
    distributions = {role: Counter() for role in roles}
    samples = {role: [] for role in roles}
    capacities = {role: {} for role in roles}
    for role, entries in sampled["roles"].items():
        for identity, (line, label) in entries.items():
            state = observation["lines"][identity]
            configured = state["configured"]
            retained = state["retained_highwater"]
            if state["line"] is not line or state["samples"] != observation["callbacks"]:
                raise AssertionError(
                    "QBuffer sampling did not follow line %s each callback" % label
                )
            if not 0 < retained <= configured:
                raise AssertionError(
                    "%s line %s had no positive in-run capacity %d/%d"
                    % (role, label, configured, retained)
                )
            capacities[role][identity] = (configured, retained)
            distributions[role][(configured, retained)] += 1
            if len(samples[role]) < 4:
                samples[role].append((label, configured, retained))

    for identity in sampled["direct_inputs"]:
        if capacities["input"][identity] != capacities["target"][identity]:
            raise AssertionError("direct field input does not preserve target capacity")
    for role, entries in sampled["roles"].items():
        if role not in ("value", "reason"):
            continue
        other = "reason" if role == "value" else "value"
        other_by_label = {}
        for pair_id, (_pair_line, label) in sampled["roles"][other].items():
            other_by_label.setdefault(label, []).append(pair_id)
        for identity, (_line, label) in entries.items():
            paired = other_by_label.get(label)
            if (
                paired is None
                or len(paired) != 1
                or capacities[role][identity] != capacities[other][paired[0]]
            ):
                raise AssertionError("value/reason capacities differ at %s" % label)

    return {
        role: {
            "count": len(capacities[role]),
            "distribution": tuple(
                (*pair, count) for pair, count in sorted(distributions[role].items())
            ),
            "samples": tuple(samples[role]),
            **(
                {
                    "direct_target_lines": len(sampled["direct_inputs"]),
                    "derived_lines": len(sampled["derived_inputs"]),
                }
                if role == "input"
                else {}
            ),
        }
        for role in roles
    }


def _assert_qbuffer_profile(profile):
    """Check capacity distributions and the feed/input and value/reason ties."""
    assert tuple(profile) == ("target", "input", "value", "reason")
    for role, receipt in profile.items():
        assert receipt["count"] > 0, "no actual QBuffer lines for role %s" % role
        assert receipt["distribution"]
        assert receipt["samples"]
        assert sum(count for _configured, _retained, count in receipt["distribution"]) == (
            receipt["count"]
        )
        assert all(
            0 < retained <= configured and count > 0
            for configured, retained, count in receipt["distribution"]
        ), ("invalid configured/retained QBuffer capacity for role %s" % role)

    assert profile["input"]["direct_target_lines"] > 0

    value_pairs = {
        (configured, retained): count
        for configured, retained, count in profile["value"]["distribution"]
    }
    reason_pairs = {
        (configured, retained): count
        for configured, retained, count in profile["reason"]["distribution"]
    }
    assert (
        value_pairs == reason_pairs
    ), "operator values/reasons have different capacity distributions"
    configured_capacities = {
        configured
        for receipt in profile.values()
        for configured, _retained, _count in receipt["distribution"]
    }
    assert (
        len(configured_capacities) > 1
    ), "actual target/input/operator buffers did not exhibit distinct configured capacities"


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
                        "%s NaN mask differs at row %d asset %d" % (label, row_index, asset_index)
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

    capacity_observation = {}
    patch = pytest.MonkeyPatch()
    try:
        queued_strategy, queued_streams = _run_alpha101_buffer_batch(
            patch,
            frames,
            alpha_ids,
            mode="native",
            exactbars=1,
            retain_tokens=True,
            capacity_observation=capacity_observation,
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
    capacity_profile = _qbuffer_profile(queued_strategy, capacity_observation)
    _assert_qbuffer_profile(capacity_profile)
    actual_max = max(
        retained
        for receipt in capacity_profile.values()
        for _configured, retained, _count in receipt["distribution"]
    )
    assert actual_max > 0
    print(
        "Alpha101 qbuffer prefix complete: mode=native formulas=%d-%d rows=%d "
        "actual_max_retained=%d complete_wraps=%d capacity_distribution=%r"
        % (
            alpha_ids[0],
            alpha_ids[-1],
            len(grid),
            actual_max,
            len(grid) // actual_max,
            {
                role: {
                    "distribution": receipt["distribution"],
                    "samples": receipt["samples"],
                    **(
                        {
                            "direct_target_lines": receipt["direct_target_lines"],
                            "derived_lines": receipt["derived_lines"],
                        }
                        if role == "input"
                        else {}
                    ),
                }
                for role, receipt in capacity_profile.items()
            },
        ),
        flush=True,
    )


def test_alpha101_maxlen_one_samples_during_run_before_eof_empties_buffer(monkeypatch):
    """Alpha101's unused-at-next-callback tail still had a populated maxlen-1 buffer."""
    frames = _alpha101_long_gap_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)

    for mode in ("native", "build"):
        full_strategy, full_streams = _run_alpha101_buffer_batch(
            monkeypatch, frames, (101,), mode=mode, exactbars=0
        )
        capacity_observation = {}
        queued_strategy, queued_streams = _run_alpha101_buffer_batch(
            monkeypatch,
            frames,
            (101,),
            mode=mode,
            exactbars=1,
            capacity_observation=capacity_observation,
        )
        assert set(full_streams) == set(queued_streams)
        assert _first_stream_difference(full_streams, queued_streams) is None
        _assert_exact_matrices(
            _panel_factor_matrix(full_strategy, 101, grid, assets),
            _panel_factor_matrix(queued_strategy, 101, grid, assets),
            label="Alpha101 %s T320 full/qbuffer result" % mode,
        )

        values = _panel_factor_matrix(queued_strategy, 101, grid, assets)
        finite = [float(value) for row in values for value in row if math.isfinite(float(value))]
        assert finite and any(value != 0.0 for value in finite)

        factor = queued_strategy.factor_instances["alpha101"]
        target_close = queued_strategy.datas[0].close
        factor_close = factor._field_line_cache["close"][0]
        assert factor_close is target_close
        close_sample = capacity_observation["lines"][id(target_close)]
        assert close_sample["line"] is target_close
        assert close_sample["configured"] == target_close.maxlen == 1
        assert close_sample["retained_highwater"] == 1
        assert close_sample["samples"] == len(grid)
        assert len(grid) >= 10 * close_sample["retained_highwater"]

        # Cerebro's normal EOF rollback may leave a one-slot QBuffer empty.
        # That terminal state is distinct from its observed in-run capacity.
        assert target_close.buflen() == 0
        assert len(target_close.array) - int(target_close.extension) == 0
        assert target_close.lencount == len(grid)
        profile = _qbuffer_profile(queued_strategy, capacity_observation)
        _assert_qbuffer_profile(profile)
        assert all(
            len(grid) >= 10 * retained
            for receipt in profile.values()
            for _configured, retained, _count in receipt["distribution"]
        ), "not every observed QBuffer high-water wrapped ten times"


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
                assert any(
                    value != 0.0 for value in finite
                ), "Alpha%d %s full run has only zero post-H values" % (alpha_id, mode)
                full_matrices[alpha_id] = actual

            capacity_observation = {}
            queued_strategy, queued_streams = _run_alpha101_buffer_batch(
                monkeypatch,
                frames,
                batch,
                mode=mode,
                exactbars=1,
                capacity_observation=capacity_observation,
            )
            capacity_profile = _qbuffer_profile(queued_strategy, capacity_observation)
            _assert_qbuffer_profile(capacity_profile)
            max_configured = max(
                configured
                for receipt in capacity_profile.values()
                for configured, _retained, _count in receipt["distribution"]
            )
            max_retained = max(
                retained
                for receipt in capacity_profile.values()
                for _configured, retained, _count in receipt["distribution"]
            )
            lane_capacity_receipts[(mode, batch[0], batch[-1])] = {
                "configured_maxlen": max_configured,
                "actual_retained_max": max_retained,
                "complete_wraps": rows // max_retained,
                "by_role": capacity_profile,
            }
            assert max_retained > 0
            assert rows >= max(1280, 10 * max_retained), (
                "Alpha101 %s/%d-%d fixture does not wrap its actual max retained capacity "
                "ten times: rows=%d actual_max=%d" % (mode, batch[0], batch[-1], rows, max_retained)
            )
            if full_streams.keys() != queued_streams.keys():
                missing = sorted(set(full_streams) ^ set(queued_streams), key=repr)
                raise AssertionError(
                    "%s node inventory changed with qbuffer: %r" % (mode, missing[:8])
                )
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
                assert any(
                    value != 0.0 for value in finite
                ), "Alpha%d %s qbuffer run has only zero post-H values" % (alpha_id, mode)

            print(
                "Alpha101 qbuffer lane complete: mode=%s formulas=%d-%d rows=%d "
                "configured_maxlen=%d actual_max_retained=%d complete_wraps=%d "
                "capacity_distribution=%r"
                % (
                    mode,
                    batch[0],
                    batch[-1],
                    rows,
                    max_configured,
                    max_retained,
                    rows // max_retained,
                    {
                        role: {
                            "distribution": receipt["distribution"],
                            "samples": receipt["samples"],
                            **(
                                {
                                    "direct_target_lines": receipt["direct_target_lines"],
                                    "derived_lines": receipt["derived_lines"],
                                }
                                if role == "input"
                                else {}
                            ),
                        }
                        for role, receipt in capacity_profile.items()
                    },
                ),
                flush=True,
            )

    assert len(lane_capacity_receipts) == len(batches) * 2
    assert all(receipt["actual_retained_max"] > 0 for receipt in lane_capacity_receipts.values())
    assert all(receipt["complete_wraps"] >= 10 for receipt in lane_capacity_receipts.values())
