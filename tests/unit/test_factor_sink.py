"""Contract tests for FactorSink and the lightweight align_to_grid path."""

from __future__ import annotations

from array import array

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import DatasetError, ResearchConfigError
from backtrader.research.align import align_to_grid
from backtrader.research.sink import CsvSink, MemorySink, PanelContext
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


def test_on_point_is_rejected_after_finalize():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    for time in context.grid.index:
        for asset in context.target_order:
            sink.on_point(time, asset, {"f1": 1.0, "f2": 2.0}, 1.0, 2.0, True)
    sink.finalize(context)
    with pytest.raises(RuntimeError, match="sink is finalized"):
        sink.on_point(context.grid.index[-1], "000001", {"f1": 3.0, "f2": 4.0}, 1.0, 2.0, True)


def test_csv_sink_finalize_and_write_are_idempotent(tmp_path):
    research = make_research()
    context = make_context(research)
    sink = CsvSink(tmp_path / "panel")
    for time in context.grid.index:
        for asset in context.target_order:
            sink.on_point(time, asset, {"f1": 1.0, "f2": 2.0}, 1.0, 2.0, True)

    panel = sink.finalize(context)
    first_contents = {path.name: path.read_bytes() for path in (tmp_path / "panel").iterdir()}
    assert sink.finalize(context) is panel
    sink.write(panel)
    sink.close()
    sink.close()
    assert sink.finalize(context) is panel
    assert {
        path.name: path.read_bytes() for path in (tmp_path / "panel").iterdir()
    } == first_contents


def test_csv_sink_does_not_replace_an_existing_target(tmp_path):
    research = make_research()
    context = make_context(research)
    memory = MemorySink()
    for time in context.grid.index:
        for asset in context.target_order:
            memory.on_point(time, asset, {"f1": 1.0, "f2": 2.0}, 1.0, 2.0, True)
    panel = memory.finalize(context)

    target = tmp_path / "panel"
    target.mkdir()
    marker = target / "owned-by-caller.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(DatasetError, match="already exists"):
        CsvSink(target).write(panel)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in target.iterdir()) == ["owned-by-caller.txt"]


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


def test_memory_sink_keeps_float64_columns_and_preserves_conversion_order():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    events = []

    class TrackedFloat:
        def __init__(self, label, value):
            self.label = label
            self.value = value

        def __float__(self):
            events.append(self.label)
            return self.value

    class TrackedPresence:
        def __bool__(self):
            events.append("present")
            return False

    first_time = context.grid.index[0]
    sink.on_point(
        first_time,
        context.target_order[0],
        {"f1": TrackedFloat("f1", 1.25), "f2": TrackedFloat("f2", -2.5)},
        TrackedFloat("open", 10.0),
        TrackedFloat("close", 11.0),
        TrackedPresence(),
    )
    assert events == ["f1", "f2", "open", "close", "present"]
    assert all(type(column) is array and column.typecode == "d" for column in sink._values)
    assert type(sink._open) is array and sink._open.typecode == "d"
    assert type(sink._close) is array and sink._close.typecode == "d"
    assert not hasattr(sink, "_present")

    for time in context.grid.index:
        for asset in context.target_order:
            if time == first_time and asset == context.target_order[0]:
                continue
            sink.on_point(time, asset, {"f1": 1.25, "f2": -2.5}, 10.0, 11.0, True)

    panel = sink.finalize(context)
    assert tuple(panel.factors.dtypes.astype(str)) == ("float64", "float64")
    assert panel.factors.iloc[0].tolist() == [1.25, -2.5]


def test_memory_sink_keeps_duplicate_rejection_at_finalize():
    research = make_research()
    context = make_context(research)
    sink = MemorySink()
    time = context.grid.index[0]
    for _ in range(2):
        sink.on_point(time, context.target_order[0], {"f1": 1.0, "f2": 2.0}, 10.0, 11.0, True)

    with pytest.raises(DatasetError, match="duplicate \\(time, asset\\) keys"):
        sink.finalize(context)


def test_memory_sink_preserves_empty_factor_and_failed_conversion_boundaries():
    research = make_research()
    context = make_context(research)
    empty_sink = MemorySink()
    for time in context.grid.index:
        for asset in context.target_order:
            empty_sink.on_point(time, asset, {}, 10.0, 11.0, True)
    empty_context = PanelContext(
        grid=context.grid,
        start=context.start,
        end=context.end,
        target_order=context.target_order,
        factor_order=(),
        directions={},
        prices_open=context.prices_open,
        prices_close=context.prices_close,
    )
    with pytest.raises(ResearchConfigError, match="at least one factor column"):
        empty_sink.finalize(empty_context)

    transition_sink = MemorySink()
    transition_sink.on_point(context.grid.index[0], context.target_order[0], {}, 10.0, 11.0, True)
    transition_sink.on_point(
        context.grid.index[0], context.target_order[1], {"f1": 1.0}, 10.0, 11.0, True
    )
    with pytest.raises(IndexError, match="tuple index out of range"):
        transition_sink.finalize(
            PanelContext(
                grid=context.grid,
                start=context.start,
                end=context.end,
                target_order=context.target_order,
                factor_order=("f1",),
                directions={"f1": 1},
                prices_open=context.prices_open,
                prices_close=context.prices_close,
            )
        )

    class InvalidFloat:
        def __float__(self):
            raise ValueError("conversion failed")

    failed_sink = MemorySink()
    with pytest.raises(ValueError, match="conversion failed"):
        failed_sink.on_point(
            context.grid.index[0],
            context.target_order[0],
            {"f1": InvalidFloat(), "f2": 2.0},
            10.0,
            11.0,
            True,
        )
    assert len(failed_sink._times) == len(failed_sink._assets) == 1
    assert all(len(column) == 0 for column in failed_sink._values)
    assert len(failed_sink._open) == len(failed_sink._close) == 0


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
