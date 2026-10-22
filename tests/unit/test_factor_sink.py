"""Contract tests for FactorSink and the lightweight align_to_grid path."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import DatasetError
from backtrader.research.align import align_to_grid
from backtrader.research.sink import MemorySink, PanelContext
from backtrader.research.specs import ResearchSpec


def make_grid(periods: int = 4) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC", name="close_time")
    return pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)


def make_research(periods: int = 4) -> ResearchSpec:
    grid = make_grid(periods)
    return ResearchSpec(
        grid=grid,
        start=grid.index[0],
        end=grid.index[-1],
        targets=("000001", "600000"),
        source_timezone="UTC",
        snapshot_id="unit",
        price_basis="raw",
        calendar_id="unit-calendar",
        frequency="1D",
    )


def make_context(research: ResearchSpec) -> PanelContext:
    grid = research.grid
    targets = research.targets
    prices = pd.DataFrame(
        np.arange(len(grid) * len(targets), dtype="float64").reshape(len(grid), len(targets)),
        index=grid.index,
        columns=list(targets),
    )
    return PanelContext(
        grid=grid,
        start=research.start,
        end=research.end,
        target_order=targets,
        factor_order=("f1", "f2"),
        directions={"f1": 1, "f2": -1},
        prices_open=prices,
        prices_close=prices + 0.5,
    )


def feed_frame(research: ResearchSpec) -> pd.DataFrame:
    grid = research.grid
    return pd.DataFrame(
        {
            "open": np.linspace(10.0, 20.0, len(grid)),
            "close": np.linspace(10.5, 20.5, len(grid)),
        },
        index=grid.index,
    )


def test_on_point_order_and_finalize_are_deterministic():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    for step, time in enumerate(context.grid.index):
        for asset in context.target_order:
            sink.on_point(
                time,
                asset,
                {"f1": float(step), "f2": float(-step)},
                float(step),
                float(step) + 1.0,
                True,
            )
    panel = sink.finalize(context)
    assert list(panel.factors.index) == list(
        pd.MultiIndex.from_product([context.grid.index, list(context.target_order)], names=("time", "asset"))
    )
    assert panel.factors["f1"].iloc[1] == 0.0
    assert panel.factor_order == ("f1", "f2")
    assert panel.directions == {"f1": 1, "f2": -1}


def test_finalize_is_idempotent_and_close_is_idempotent():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    for time in context.grid.index:
        for asset in context.target_order:
            sink.on_point(time, asset, {"f1": 1.0, "f2": 2.0}, 1.0, 2.0, True)
    first = sink.finalize(context)
    second = sink.finalize(context)
    assert first is second
    sink.close()
    sink.close()
    assert sink.panel is first
    assert sink.finalize(context) is first


def test_on_point_rejects_changed_factor_columns():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    sink.on_point(context.grid.index[0], "000001", {"f1": 1.0, "f2": 2.0}, 1.0, 2.0, True)
    with pytest.raises(DatasetError):
        sink.on_point(context.grid.index[0], "600000", {"f1": 1.0}, 1.0, 2.0, True)


def test_finalize_without_points_is_rejected():
    research = make_research()
    with pytest.raises(DatasetError):
        MemorySink().finalize(make_context(research))


def test_align_keeps_real_bars_and_marks_reindexed_rows_absent():
    research = make_research(periods=4)
    frame = feed_frame(research).drop(index=research.grid.index[1])
    aligned = align_to_grid(frame, research, "000001")
    assert list(aligned.present) == [True, False, True, True]
    assert aligned.prices_open.shape == (4,)
    assert np.isnan(aligned.prices_open[1])
    assert aligned.feed is not None
    # The caller's frame is borrowed, never mutated.
    assert len(frame) == 3
    assert frame.index.is_monotonic_increasing


def test_align_distinguishes_present_bar_with_nan_value_from_missing_bar():
    research = make_research(periods=4)
    frame = feed_frame(research)
    frame.iloc[1, frame.columns.get_loc("close")] = np.nan
    aligned = align_to_grid(frame, research, "000001")
    assert list(aligned.present) == [True, True, True, True]
    assert np.isnan(aligned.prices_close[1])


def test_align_rejects_rows_outside_the_declared_grid():
    research = make_research(periods=4)
    frame = feed_frame(research)
    outside = frame.copy()
    outside.loc[research.grid.index[-1] + pd.Timedelta(days=1)] = 1.0
    with pytest.raises(DatasetError):
        align_to_grid(outside, research, "000001")


def test_align_localizes_naive_timestamps_in_source_timezone():
    grid = make_grid(4)
    research = ResearchSpec(
        grid=grid,
        start=grid.index[0],
        end=grid.index[-1],
        targets=("000001",),
        source_timezone="Asia/Shanghai",
        snapshot_id="unit",
        price_basis="raw",
        calendar_id="unit-calendar",
        frequency="1D",
    )
    naive = grid.index.tz_convert("Asia/Shanghai").tz_localize(None)
    frame = pd.DataFrame(
        {"open": [1.0, 2.0, 3.0, 4.0], "close": [1.0, 2.0, 3.0, 4.0]}, index=naive
    )
    aligned = align_to_grid(frame, research, "000001")
    assert list(aligned.present) == [True, True, True, True]


def test_align_does_not_carry_pit_or_availability_metadata():
    research = make_research()
    aligned = align_to_grid(feed_frame(research), research, "000001")
    from backtrader.research.align import feed_alignment

    metadata = feed_alignment(aligned.feed)
    assert metadata["version"] == 2
    assert "available_at" not in metadata
    assert "present" in metadata
