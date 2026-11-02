"""Contract tests for explicit factor-research inputs and specifications."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError as ConfigError, DatasetError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research import align_to_grid
from backtrader.research.specs import FactorSpec, ResearchSpec, normalize_factor_specs


def _utc_grid() -> pd.DataFrame:
    close_time = pd.date_range(
        "2024-03-08 21:00:00", periods=5, freq="D", tz="UTC", name="close_time"
    )
    return pd.DataFrame({"open_time": close_time - pd.Timedelta(hours=6)}, index=close_time)


def _research(grid: pd.DataFrame | None = None, **overrides: Any) -> ResearchSpec:
    grid = _utc_grid() if grid is None else grid
    start_index = min(1, len(grid.index) - 1)
    end_index = min(3, len(grid.index) - 1)
    args = {
        "grid": grid,
        "start": grid.index[start_index],
        "end": grid.index[end_index],
        "targets": ("AAA", "BBB"),
        "source_timezone": "America/New_York",
        "snapshot_id": "fixture-snapshot-1",
        "price_basis": "USD spot close, unadjusted",
        "calendar_id": "fixture-calendar-v1",
        "frequency": "1session",
    }
    args.update(overrides)
    return ResearchSpec(**args)


def _bars(index: pd.DatetimeIndex, first_close: float = 10.0) -> pd.DataFrame:
    close = [first_close + 10.0 * offset for offset in range(len(index))]
    return pd.DataFrame(
        {
            "open": [value - 1.0 for value in close],
            "high": [value + 1.0 for value in close],
            "low": [value - 2.0 for value in close],
            "close": close,
            "volume": [100.0 + offset for offset in range(len(index))],
            "openinterest": [0.0] * len(index),
        },
        index=index,
    )


def _expected_keys(times: pd.DatetimeIndex, targets: tuple[str, ...]) -> pd.MultiIndex:
    return pd.MultiIndex.from_product([times, targets], names=("time", "asset"))


def test_research_spec_keeps_explicit_utc_grid_and_inclusive_ranges() -> None:
    grid = _utc_grid()
    spec = _research(grid, start=grid.index[1].tz_convert("America/New_York"))

    assert spec.grid.index.equals(grid.index)
    assert spec.grid.index.name == "close_time"
    assert str(spec.grid.index.tz) == "UTC"
    assert spec.start == grid.index[1]
    assert spec.end == grid.index[3]
    assert list(spec.calculation_grid.index) == list(grid.index[:4])
    assert len(spec.grid_sha256) == 64


def test_research_grid_hash_is_cached_and_defensive_against_grid_mutation() -> None:
    grid = _utc_grid()
    spec = _research(grid)
    expected_hash = spec.grid_sha256
    original_rows = [
        (close_time.isoformat(), open_time.isoformat())
        for close_time, open_time in zip(grid.index, grid["open_time"])
    ]
    original_payload = json.dumps(
        original_rows, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert expected_hash == hashlib.sha256(original_payload).hexdigest()

    original_index_values = grid.index.values
    private_index_values = spec._grid.index.values
    assert not np.shares_memory(original_index_values, private_index_values)
    original_first_close = spec.grid.index[0]
    _mutate_index_values_if_writable(grid.index)
    grid.index = grid.index + pd.Timedelta(days=30)
    grid.iloc[0, grid.columns.get_loc("open_time")] += pd.Timedelta(days=1)

    returned_grid = spec.grid
    returned_index_values = returned_grid.index.values
    assert not np.shares_memory(returned_index_values, private_index_values)
    _mutate_index_values_if_writable(returned_grid.index)
    returned_grid.index = returned_grid.index + pd.Timedelta(days=60)
    returned_grid.iloc[0, returned_grid.columns.get_loc("open_time")] += pd.Timedelta(
        days=2
    )

    assert spec.grid.index[0] == original_first_close
    assert spec.grid_sha256 == expected_hash
    assert spec.grid_sha256 is expected_hash


def _mutate_index_values_if_writable(index: pd.DatetimeIndex) -> None:
    values = index.values
    try:
        values.setflags(write=True)
    except ValueError:
        return
    values[0] += np.timedelta64(1, "D")


def test_research_grid_hash_is_equivalent_for_zero_offset_timezones() -> None:
    utc_grid = _utc_grid()
    zero_offset_grid = utc_grid.copy(deep=True)
    zero_offset_grid.index = utc_grid.index.tz_convert("Etc/GMT")
    zero_offset_grid["open_time"] = utc_grid["open_time"].dt.tz_convert("Etc/GMT")

    utc_spec = _research(utc_grid)
    equivalent_spec = _research(
        zero_offset_grid,
        start=zero_offset_grid.index[1],
        end=zero_offset_grid.index[3],
    )

    assert utc_spec.grid_sha256 == equivalent_spec.grid_sha256






@pytest.mark.parametrize(
    "overrides",
    [
        {"targets": ("AAA", "AAA")},
        {"targets": ("AAA", " ")},
        {"source_timezone": "Not/A_Real_Zone"},
        {"snapshot_id": ""},
        {"price_basis": "default"},
        {"calendar_id": ""},
        {"frequency": ""},
        {"feed_time_kind": "open_time"},
        {"groups": {"AAA": "growth"}},
        {"execution": "next"},
    ],
)
def test_research_spec_rejects_duplicate_empty_or_unsupported_config(
    overrides: Mapping[str, Any],
) -> None:
    with pytest.raises(ConfigError):
        _research(**dict(overrides))


def test_research_spec_rejects_naive_range_endpoints_and_non_utc_grid() -> None:
    grid = _utc_grid()
    with pytest.raises(ConfigError, match="timezone"):
        _research(grid, start="2024-03-09 21:00:00")

    local_grid = grid.copy()
    local_grid.index = local_grid.index.tz_convert("America/New_York")
    with pytest.raises(ConfigError, match="UTC"):
        _research(local_grid)




@pytest.mark.parametrize(
    "local_time",
    ["2024-11-03 01:30", "2024-03-10 02:30"],
)
def test_prealign_bars_rejects_ambiguous_or_nonexistent_local_dst_times(
    local_time: str,
) -> None:
    grid = pd.DataFrame(
        {"open_time": [pd.Timestamp("2024-11-03 00:00", tz="UTC")]},
        index=pd.DatetimeIndex(["2024-11-03 01:00"], tz="UTC", name="close_time"),
    )
    research = _research(
        grid,
        start=grid.index[0],
        end=grid.index[0],
    )
    source = _bars(pd.DatetimeIndex([local_time], name="close_time"))

    with pytest.raises(DatasetError):
        align_to_grid(source, research, "AAA")




class _SpecFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = (
        "close",
        "benchmark_close",
        "dollar_volume",
        "vwap",
        "volume",
        "adv20",
    )
    classification_fields = ("sector",)
    classification_levels = ("sector",)
    lookback_h = 2

    def next(self) -> None:
        pass


def _factor_spec(field_bindings: Mapping[str, Any], **overrides: Any) -> FactorSpec:
    args = {
        "name": "fixture_factor",
        "indicator": _SpecFactor,
        "panel_line": "factor",
        "field_bindings": field_bindings,
    }
    args.update(overrides)
    return FactorSpec(**args)






