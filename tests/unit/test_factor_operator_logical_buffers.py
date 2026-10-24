"""Logical grid indexing contracts for research operators over qbuffers."""

import math
import struct
from types import SimpleNamespace

import pandas as pd

import backtrader as bt
import backtrader.research.operators as operators
from backtrader.linebuffer import LineBuffer
from backtrader.research import align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.research.operators import OperatorReason
from backtrader.research.specs import ResearchSpec


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
