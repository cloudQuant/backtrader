"""Bounded lifecycle diagnostics and explicit full-trace capture contracts."""

from collections import deque

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorIndicator, FactorSpec, ResearchSpec, align_to_grid
from backtrader.research.factor_indicator import _factor_diagnostic_history_capture
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.test_utils.alpha101_trace_validation import _require_captured_factor_trace


class _DiagnosticChild(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.close_lines = self.field_lines("close")

    def next(self):
        for data, close in zip(self.target_datas, self.close_lines):
            self.outputs[data].factor[0] = close[0]


class _DiagnosticBridge(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.child = _DiagnosticChild.bind(*self.datas)

    def next(self):
        self.lines.value[0] = self.child.outputs[self.datas[0]].factor[0]


class _DiagnosticFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.bridge = _DiagnosticBridge(self.datas[0])

    def next(self):
        for data in self.target_datas:
            self.outputs[data].factor[0] = self.bridge.value[0]

def _run_factor(count=96, *, capture=False):
    grid = pd.date_range(
        "2026-11-01 09:30", periods=count, freq="min", tz="UTC", name="close_time"
    )
    frame = pd.DataFrame(
        {
            "open": range(100, 100 + count),
            "high": range(101, 101 + count),
            "low": range(99, 99 + count),
            "close": range(100, 100 + count),
            "volume": [1000.0] * count,
        },
        index=grid,
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": grid - pd.Timedelta(minutes=1)}, index=grid),
        start=grid[0],
        end=grid[-1],
        targets=("A",),
        source_timezone="UTC",
        snapshot_id="factor-diagnostics-bounded",
        price_basis="unadjusted close",
        calendar_id="minute-fixture",
        frequency="1min",
    )
    spec = FactorSpec(
        name="diagnostic",
        indicator=_DiagnosticFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(align_to_grid(frame, research, "A").feed, name="A")
    cerebro.addstrategy(FactorStrategy, research=research, factors={"diagnostic": spec})
    if capture:
        with _factor_diagnostic_history_capture():
            strategy = cerebro.run()[0]
    else:
        strategy = cerebro.run()[0]
    return strategy.factor_instances["diagnostic"], tuple(grid.to_pydatetime())


def test_offline_calls_keep_only_bounded_actual_samples_but_full_counters():
    factor, grid = _run_factor()
    diagnostics = factor.lifecycle_diagnostics

    assert type(factor._factor_call_times) is deque
    assert factor._factor_call_times.maxlen == 64
    assert factor._factor_call_count == len(grid) == 96
    assert tuple(diagnostics["call_times"]) == grid[-64:]
    assert diagnostics["call_times_source"] == "actual_bounded_sample"
    assert diagnostics["call_times_truncated"] is True
    assert diagnostics["call_count"] == diagnostics["coverage_count"] == 96
    assert diagnostics["coverage_matches"] is True
    assert diagnostics["coverage_times"] == diagnostics["call_times"]
    assert diagnostics["coverage_times_truncated"] is True
    assert diagnostics["expected_coverage_times_sample"] == grid[-64:]
    assert diagnostics["expected_coverage_times_sample_source"] == "validated_grid_sample"
    facts = factor.lifecycle_capacity_facts
    assert facts["status"] == "OBSERVED"
    assert facts["call_count"] == 96
    assert facts["call_sample_count"] == 64
    assert facts["sample_limit"] == 64


def test_every_factor_and_panel_operator_node_uses_bounded_default_storage():
    factor, _grid = _run_factor()
    nodes = FactorStrategy._factor_tree(factor)

    assert len(nodes) > 1
    for node in nodes:
        assert type(node._factor_call_times) is deque
        assert type(node._factor_once_ranges) is deque
        facts = node.lifecycle_capacity_facts
        assert facts["status"] == "OBSERVED"
        assert facts["sample_limit"] == 64


def test_full_trace_is_retained_only_under_explicit_capture_scope():
    factor, grid = _run_factor(capture=True)
    diagnostics = factor.lifecycle_diagnostics

    assert type(factor._factor_call_times) is list
    assert len(factor._factor_call_times) == len(grid)
    assert diagnostics["diagnostic_kind"] == "captured_offline_trace"
    assert diagnostics["call_times_source"] == "captured_actual"
    assert diagnostics["call_times_truncated"] is False
    assert diagnostics["call_times"] == grid
    assert _require_captured_factor_trace(factor) == (grid, grid)


def test_trace_validator_rejects_uncaptured_samples_as_raw_history():
    factor, _grid = _run_factor()
    with pytest.raises(AssertionError, match="requires _factor_diagnostic_history_capture"):
        _require_captured_factor_trace(factor)


def test_many_once_segments_use_counters_after_the_range_sample_truncates(monkeypatch):
    from backtrader.research import factor_indicator as lifecycle

    factor, grid = _run_factor()
    factor._factor_call_times.clear()
    factor._factor_call_count = 0
    factor._factor_once_ranges.clear()
    factor._factor_once_range_count = 0
    factor._factor_once_covered_count = 0

    # Exercise the production once wrapper for each real completed callback
    # range while isolating its unrelated panel-readiness predicate.
    monkeypatch.setattr(lifecycle, "_factor_once_supported", lambda *args: True)
    segments = tuple((index, index + 1) for index in range(len(grid)))
    for start, end in segments:
        assert lifecycle._factor_once_execute(
            factor,
            _DiagnosticFactor,
            lambda _start, _end: None,
            start,
            end,
        )

    diagnostics = factor.lifecycle_diagnostics
    assert type(factor._factor_once_ranges) is deque
    assert factor._factor_once_ranges.maxlen == 64
    assert diagnostics["once_ranges"] == segments[-64:]
    assert diagnostics["once_ranges_truncated"] is True
    assert diagnostics["once_range_count"] == 96
    assert diagnostics["once_count"] == diagnostics["coverage_count"] == 96
    assert diagnostics["coverage_matches"] is True
    assert diagnostics["grid_matches"] is False
    assert diagnostics["once_times"] == ()
    assert diagnostics["once_times_source"] is None
    assert diagnostics["once_times_truncated"] is True
    assert diagnostics["expected_coverage_times_sample"] == grid[-64:]

    with pytest.raises(RuntimeError, match="next\(\) ran after its once coverage began"):
        factor._record_factor_call()
    with pytest.raises(RuntimeError, match="gap or overlap"):
        factor._record_factor_once(len(grid) + 1, len(grid) + 2)
    factor._factor_once_ranges.clear()
    factor._factor_once_range_count = 0
    factor._factor_once_covered_count = 0
    with pytest.raises(RuntimeError, match="beyond the requested calculation grid"):
        factor._record_factor_once(0, len(grid) + 1)


def test_next_grid_mismatch_and_overrun_are_still_rejected_after_bounding():
    factor, grid = _run_factor()
    factor._factor_call_times.clear()
    factor._factor_call_count = 0
    with pytest.raises(RuntimeError, match="does not match its next UTC grid point"):
        factor._record_factor_call()
    assert factor._factor_call_count == 0
    assert not factor._factor_call_times

    factor._factor_call_count = len(grid)
    with pytest.raises(RuntimeError, match="more than once for the requested grid"):
        factor._record_factor_call()
    assert factor._factor_call_count == len(grid)
