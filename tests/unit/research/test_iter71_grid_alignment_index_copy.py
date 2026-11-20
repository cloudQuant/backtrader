"""Iteration 71 R175: align from an isolated index, not a copied grid frame."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtrader.research import align_to_grid, feed_alignment
from backtrader.research.specs import ResearchSpec


def _grid() -> pd.DataFrame:
    index = pd.date_range(
        "2026-01-01", periods=4, freq="D", tz="UTC", name="close_time"
    )
    return pd.DataFrame(
        {
            "open_time": index - pd.Timedelta(hours=6),
            "calendar_tag": ["session-a", "session-b", "session-c", "session-d"],
            "calendar_ordinal": np.arange(len(index), dtype="int64"),
        },
        index=index,
    )


def _research(grid: pd.DataFrame) -> ResearchSpec:
    return ResearchSpec(
        grid=grid,
        start=grid.index[0],
        end=grid.index[2],
        targets=("AAA", "BBB"),
        source_timezone="UTC",
        snapshot_id="iter71-r175-grid-copy",
        price_basis="synthetic unadjusted close",
        calendar_id="test-calendar-v1",
        frequency="1session",
    )


def _bars(index: pd.DatetimeIndex, base: float) -> pd.DataFrame:
    close = base + np.arange(len(index), dtype="float64")
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(len(index), 100.0),
            "openinterest": np.zeros(len(index)),
        },
        index=index,
    )


def test_public_grid_stays_a_full_defensive_copy_and_internal_index_isolated():
    input_grid = _grid()
    research = _research(input_grid)
    expected_index = input_grid.index.copy(deep=True)
    expected_tags = input_grid["calendar_tag"].tolist()

    index_copy = research._copy_grid_index_for_alignment()
    assert isinstance(index_copy, pd.DatetimeIndex)
    assert index_copy.equals(expected_index)
    assert not np.shares_memory(index_copy.asi8, research._grid.index.asi8)

    public_grid = research.grid
    assert list(public_grid.columns) == list(input_grid.columns)
    assert public_grid["calendar_tag"].tolist() == expected_tags
    assert not np.shares_memory(public_grid.index.asi8, research._grid.index.asi8)

    public_grid["calendar_ordinal"] = -1
    public_grid.index = public_grid.index + pd.Timedelta(days=10)
    assert research.grid["calendar_ordinal"].tolist() == [0, 1, 2, 3]
    assert research.grid.index.equals(expected_index)
    assert input_grid.index.equals(expected_index)


def test_alignment_preserves_rows_prices_metadata_and_does_not_copy_grid_columns():
    grid = _grid()
    research = _research(grid)
    aaa = _bars(grid.index[[0, 2, 3]], 10.0)
    bbb = _bars(grid.index[[1, 2]], 20.0)

    aligned_aaa = align_to_grid(aaa, research, "AAA", data_version="bars-v1")
    aligned_bbb = align_to_grid(bbb, research, "BBB", data_version="bars-v1")

    expected_aaa = aaa.reindex(grid.index[:3])
    expected_bbb = bbb.reindex(grid.index[:3])
    pd.testing.assert_frame_equal(aligned_aaa.feed.p.dataname, expected_aaa)
    pd.testing.assert_frame_equal(aligned_bbb.feed.p.dataname, expected_bbb)
    assert list(aligned_aaa.feed.p.dataname.columns) == list(aaa.columns)
    assert "calendar_tag" not in aligned_aaa.feed.p.dataname
    assert "calendar_ordinal" not in aligned_aaa.feed.p.dataname

    assert aligned_aaa.present.tolist() == [True, False, True]
    assert aligned_bbb.present.tolist() == [False, True, True]
    np.testing.assert_allclose(
        aligned_aaa.prices_open,
        [9.5, np.nan, 10.5, 11.5],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        aligned_aaa.prices_close,
        [10.0, np.nan, 11.0, 12.0],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        aligned_bbb.prices_close,
        [np.nan, 20.0, 21.0, np.nan],
        equal_nan=True,
    )
    assert aligned_aaa.grid_sha256 == aligned_bbb.grid_sha256 == research.grid_sha256
    assert aligned_aaa.data_version == aligned_bbb.data_version == "bars-v1"

    aaa_metadata = feed_alignment(aligned_aaa.feed)
    bbb_metadata = feed_alignment(aligned_bbb.feed)
    assert aaa_metadata["asset"] == "AAA"
    assert bbb_metadata["asset"] == "BBB"
    assert aaa_metadata["present"].tolist() == [True, False, True]
    assert bbb_metadata["present"].tolist() == [False, True, True]
    assert set(aaa_metadata["field_present"]) == set(aaa.columns)
    assert all(
        values.tolist() == [True, False, True]
        for values in aaa_metadata["field_present"].values()
    )
    assert all(
        values.tolist() == [False, True, True]
        for values in bbb_metadata["field_present"].values()
    )


def test_aligned_feed_index_write_cannot_mutate_spec_or_another_asset():
    grid = _grid()
    research = _research(grid)
    aaa = _bars(grid.index, 10.0)
    bbb = _bars(grid.index, 20.0)
    aligned_aaa = align_to_grid(aaa, research, "AAA")
    aligned_bbb = align_to_grid(bbb, research, "BBB")

    original_spec_index = research._grid.index.copy(deep=True)
    original_bbb_index = aligned_bbb.feed.p.dataname.index.copy(deep=True)
    writable_values = aligned_aaa.feed.p.dataname.index.asi8
    try:
        writable_values.setflags(write=True)
    except ValueError:
        pytest.skip("this pandas version exposes an immutable datetime index buffer")
    writable_values[0] += int(pd.Timedelta(minutes=1).value)

    assert research._grid.index.equals(original_spec_index)
    assert aligned_bbb.feed.p.dataname.index.equals(original_bbb_index)
    assert aaa.index.equals(grid.index)
    assert bbb.index.equals(grid.index)


def test_alignment_keeps_a_research_spec_grid_property_override():
    grid = _grid()

    class OverriddenGridResearchSpec(ResearchSpec):
        @property
        def grid(self):
            overridden = super().grid
            overridden.index = overridden.index - pd.Timedelta(hours=1)
            return overridden

    base = _research(grid)
    research = OverriddenGridResearchSpec(
        grid=grid,
        start=base.start,
        end=base.end,
        targets=base.targets,
        source_timezone=base.source_timezone,
        snapshot_id="subclass-grid",
        price_basis=base.price_basis,
        calendar_id=base.calendar_id,
        frequency=base.frequency,
    )
    source_index = grid.index - pd.Timedelta(hours=1)
    source = _bars(source_index, 30.0)

    aligned = align_to_grid(source, research, "AAA")

    assert aligned.feed.p.dataname.index.equals(source_index[:3])
    assert aligned.present.tolist() == [True, True, True]
