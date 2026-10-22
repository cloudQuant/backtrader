"""Focused source-metadata checks for DS45-12 ADV and VWAP inputs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError as ConfigError, DatasetError
from backtrader.research.field_validation import (
    collect_bound_feed_tables,
    validate_factor_field_metadata,
)
from backtrader.research.inputs import prealign_bars
from backtrader.research.specs import ResearchSpec


def _table(metadata: Mapping[str, Any], *, columns: tuple[str, ...] = ()) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02", tz="UTC"), "AAA")], names=("time", "asset")
    )
    values = {"value": [1.0], "available_at": [index[0][0]], "data_version": ["fixture-v1"]}
    values.update({column: [None] for column in columns})
    frame = pd.DataFrame(values, index=index)
    frame.attrs["source_metadata"] = dict(metadata)
    return frame


def _direct_adv_metadata(**overrides: Any) -> dict[str, Any]:
    metadata = {
        "name": "adv20",
        "semantic": "average_daily_dollar_volume",
        "unit": "USD",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
        "statistic": "mean",
        "window": 20,
        "complete_window": True,
        "source_version": "vendor-snapshot-v1",
        "provenance_source_lookback_grid_bars": 19,
    }
    metadata.update(overrides)
    return metadata


def _vwap_metadata(**overrides: Any) -> dict[str, Any]:
    metadata = {
        "name": "vwap",
        "semantic": "volume_weighted_average_price",
        "unit": "USD per share",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
        "statistic": "trade_volume_weighted_mean",
    }
    metadata.update(overrides)
    return metadata


def _volume_metadata(**overrides: Any) -> dict[str, Any]:
    metadata = {
        "name": "volume",
        "semantic": "share_volume",
        "unit": "shares",
        "adjustment": "split-adjusted-v1",
    }
    metadata.update(overrides)
    return metadata


def _validate(
    field_bindings: Mapping[str, Any], formula_fields: Mapping[str, pd.DataFrame]
) -> None:
    spec = SimpleNamespace(name="fixture", field_bindings=field_bindings)
    research = SimpleNamespace(formula_fields=formula_fields)
    validate_factor_field_metadata(spec, research, (), ())


def test_direct_adv_accepts_full_source_metadata_and_keeps_direct_binding() -> None:
    frame = _table(_direct_adv_metadata())
    original_binding = "table:adv20_usd"

    _validate({"adv20": original_binding}, {"adv20_usd": frame})

    assert frame.attrs["source_metadata"]["statistic"] == "mean"


def test_direct_adv_accepts_explicit_row_availability_on_feed_frame() -> None:
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    frame = pd.DataFrame(
        {
            "adv2": [10.0],
            "available_at": [timestamp],
            "data_version": ["fixture-v1"],
        },
        index=pd.DatetimeIndex([timestamp]),
    )
    frame.attrs["source_metadata"] = _direct_adv_metadata(
        name="adv2", window=2, provenance_source_lookback_grid_bars=1
    )
    feed = SimpleNamespace(_name="AAA", p=SimpleNamespace(dataname=frame))
    spec = SimpleNamespace(name="fixture", field_bindings={"adv2": "feed:target:adv2"})
    research = SimpleNamespace(formula_fields={})

    validate_factor_field_metadata(spec, research, (feed,), (feed,))


def test_direct_adv_rejects_a_nonpositive_window_in_the_field_name() -> None:
    with pytest.raises(ConfigError):
        _validate(
            {"adv0": "table:adv0_usd"},
            {"adv0_usd": _table(_direct_adv_metadata(name="adv0", window=0))},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"window": 10},
        {"complete_window": False},
        {"unit": "shares"},
        {"currency": "EUR"},
        {"statistic": "sum"},
        {"provenance_source_lookback_grid_bars": 20},
        {"adjustment": ""},
    ],
)
def test_direct_adv_rejects_incompatible_metadata(overrides: Mapping[str, Any]) -> None:
    with pytest.raises(ConfigError):
        _validate(
            {"adv20": "table:adv20_usd"},
            {"adv20_usd": _table(_direct_adv_metadata(**dict(overrides)))},
        )


@pytest.mark.parametrize("missing", ["source_version", "available_at", "data_version"])
def test_direct_adv_rejects_missing_provenance_or_pit_fields(missing: str) -> None:
    metadata = _direct_adv_metadata()
    frame = _table(metadata)
    if missing == "source_version":
        metadata.pop(missing)
        frame.attrs["source_metadata"] = metadata
    else:
        frame = frame.drop(columns=[missing])

    with pytest.raises(DatasetError) as error:
        _validate({"adv20": "table:adv20_usd"}, {"adv20_usd": frame})

    assert error.value.code == "MISSING_INPUT"


@pytest.mark.parametrize("column", ["available_at", "data_version"])
def test_direct_adv_rejects_missing_values_in_required_pit_columns(column: str) -> None:
    frame = _table(_direct_adv_metadata())
    frame.loc[:, column] = None

    with pytest.raises(DatasetError) as error:
        _validate({"adv20": "table:adv20_usd"}, {"adv20_usd": frame})

    assert error.value.code == "MISSING_INPUT"


def _vwap_volume_bindings() -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    bindings = {
        "dollar_volume": {"derive": "vwap_volume", "vwap": "vwap", "volume": "volume"},
        "vwap": "table:vwap_table",
        "volume": "table:volume_table",
        "adv20": {"derive": "adv", "source": "dollar_volume", "window": 20},
    }
    tables = {
        "vwap_table": _table(_vwap_metadata()),
        "volume_table": _table(_volume_metadata()),
    }
    return bindings, tables


def test_explicit_vwap_volume_and_derived_adv_accept_compatible_units() -> None:
    bindings, tables = _vwap_volume_bindings()

    _validate(bindings, tables)


@pytest.mark.parametrize(
    "vwap_overrides,volume_overrides",
    [
        ({"unit": "USD"}, {}),
        ({"semantic": "ohlc_average"}, {}),
        ({"currency": "EUR"}, {}),
        ({}, {"unit": "contracts"}),
        ({"adjustment": "unadjusted"}, {}),
        ({}, {"adjustment": "unadjusted"}),
    ],
)
def test_vwap_volume_rejects_approximations_and_incompatible_units(
    vwap_overrides: Mapping[str, Any], volume_overrides: Mapping[str, Any]
) -> None:
    bindings, tables = _vwap_volume_bindings()
    tables["vwap_table"] = _table(_vwap_metadata(**dict(vwap_overrides)))
    tables["volume_table"] = _table(_volume_metadata(**dict(volume_overrides)))

    with pytest.raises(ConfigError):
        _validate(bindings, tables)


def test_adv_rejects_a_close_volume_product_without_explicit_dollar_volume_semantics() -> None:
    bindings = {
        "dollar_volume": "table:close_table",
        "adv20": {"derive": "adv", "source": "dollar_volume", "window": 20},
    }
    close_metadata = {
        "name": "dollar_volume",
        "semantic": "close_price",
        "unit": "USD per share",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
    }

    with pytest.raises(ConfigError):
        _validate(bindings, {"close_table": _table(close_metadata)})


def _feed(name: str, frame: pd.DataFrame, *, marker: Mapping[str, Any] | None = None) -> Any:
    feed = SimpleNamespace(_name=name, p=SimpleNamespace(dataname=frame))
    if marker is not None:
        setattr(feed, "_factor_research_alignment_v1", marker)
    return feed


def _collection_research(
    grid: pd.DatetimeIndex,
    targets: tuple[str, ...],
    *,
    feed_time_kind: str | None = None,
) -> Any:
    return SimpleNamespace(
        targets=targets,
        source_timezone="UTC",
        grid_sha256="fixture-grid-v1",
        snapshot_id="snapshot-v1",
        feed_time_kind=feed_time_kind,
        calculation_grid=pd.DataFrame(index=grid),
    )


def test_collection_preserves_full_prealigned_target_rows_and_source_feeds() -> None:
    grid = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA", "BBB"))
    feeds = []
    for asset, base in (("AAA", 10.0), ("BBB", 20.0)):
        frame = pd.DataFrame({"close": [base, base + 1, base + 2]}, index=grid)
        frame.attrs["source_metadata"] = {
            "name": "close",
            "semantic": "adjusted_close_price",
            "unit": "USD per share",
            "currency": "USD",
            "adjustment": "split-adjusted-v1",
        }
        marker = {
            "grid_sha256": "fixture-grid-v1",
            "present": (True, True, True),
            "available_at": tuple(grid.to_pydatetime()),
            "data_version": "bars-v1",
        }
        feeds.append(_feed(asset, frame, marker=marker))

    tables = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
        research,
        feeds,
        feeds,
    )

    table = tables["feed:target:close"]
    assert len(table) == len(grid) * 2
    assert table.loc[(grid[1], "AAA"), "value"] == 11.0
    assert table.loc[(grid[2], "BBB"), "value"] == 22.0
    assert table.loc[(grid[1], "AAA"), "available_at"] == grid[1]
    assert table.loc[(grid[1], "AAA"), "data_version"] == "bars-v1"
    assert set(table["source_feed"]) == {"AAA", "BBB"}
    assert table.attrs["source_metadata"]["semantic"] == "adjusted_close_price"
    assert table.attrs["source_metadata"]["source_binding"] == "feed:target:close"


def test_collection_broadcasts_only_explicit_named_feed_over_targets() -> None:
    grid = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA", "BBB"))
    targets = [
        _feed(asset, pd.DataFrame({"close": [1.0, 2.0]}, index=grid)) for asset in research.targets
    ]
    benchmark_frame = pd.DataFrame(
        {
            "close": [100.0, 101.0],
            "available_at": grid,
            "data_version": ["benchmark-v4", "benchmark-v4"],
        },
        index=grid,
    )
    benchmark = _feed("SPY", benchmark_frame)

    tables = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"benchmark": "feed:SPY:close"})],
        research,
        targets + [benchmark],
        targets,
    )

    table = tables["feed:SPY:close"]
    assert len(table) == len(grid) * len(research.targets)
    assert table.loc[(grid[1], "AAA"), "value"] == 101.0
    assert table.loc[(grid[1], "BBB"), "value"] == 101.0
    assert set(table["source_feed"]) == {"SPY"}
    assert table.attrs["source_metadata"]["source_feed"] == "SPY"


def test_collection_expands_only_declared_derived_feed_sources() -> None:
    specs = [
        SimpleNamespace(
            field_bindings={
                "adv2": {"derive": "adv", "source": "dollar_volume", "window": 2},
                "dollar_volume": {
                    "derive": "vwap_volume",
                    "vwap": "vwap",
                    "volume": "volume",
                },
                "vwap": "feed:target:vwap",
                "volume": "feed:BENCH:volume",
                "unused": "table:already_aligned",
            }
        )
    ]
    grid = pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA",), feed_time_kind="close_time")
    target = _feed("AAA", pd.DataFrame({"vwap": [10.0]}, index=grid))
    benchmark = _feed(
        "BENCH",
        pd.DataFrame(
            {"volume": [2.0], "available_at": grid, "data_version": ["bench-v1"]},
            index=grid,
        ),
    )

    tables = collect_bound_feed_tables(specs, research, (target, benchmark), (target,))

    assert set(tables) == {"feed:target:vwap", "feed:BENCH:volume"}
    assert tables["feed:target:vwap"].loc[(grid[0], "AAA"), "value"] == 10.0
    assert tables["feed:BENCH:volume"].loc[(grid[0], "AAA"), "value"] == 2.0
    assert tables["feed:target:vwap"].loc[(grid[0], "AAA"), "available_at"] == grid[0]
    assert tables["feed:target:vwap"].loc[(grid[0], "AAA"), "data_version"] == "snapshot-v1"
    assert (
        tables["feed:target:vwap"].attrs["source_metadata"]["data_version_source"]
        == "research.snapshot_id"
    )


def test_collection_fails_closed_without_real_availability_and_version() -> None:
    grid = pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA",))
    feed = _feed("AAA", pd.DataFrame({"close": [10.0]}, index=grid))

    with pytest.raises(DatasetError) as error:
        collect_bound_feed_tables(
            [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
            research,
            (feed,),
            (feed,),
        )

    assert error.value.code == "MISSING_INPUT"
    assert "availability" in str(error.value)


def test_collection_keeps_sparse_prealigned_feed_gaps_without_invented_times() -> None:
    grid = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA",))
    frame = pd.DataFrame({"close": [10.0, float("nan"), 12.0]}, index=grid)
    marker = {
        "grid_sha256": "fixture-grid-v1",
        "present": (True, False, True),
        "available_at": (grid[0].to_pydatetime(), None, grid[2].to_pydatetime()),
        "data_version": "bars-v1",
    }
    feed = _feed("AAA", frame, marker=marker)

    table = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
        research,
        (feed,),
        (feed,),
    )["feed:target:close"]

    assert list(table.index.get_level_values("time")) == [grid[0], grid[2]]


def test_collection_uses_alignment_marker_when_explicit_pit_columns_are_missing() -> None:
    grid = pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC")
    research = _collection_research(grid, ("AAA",))
    frame = pd.DataFrame(
        {"close": [10.0], "available_at": [pd.NaT], "data_version": [None]}, index=grid
    )
    marker = {
        "grid_sha256": "fixture-grid-v1",
        "present": (True,),
        "available_at": (grid[0].to_pydatetime(),),
        "data_version": "aligned-v3",
    }
    feed = _feed("AAA", frame, marker=marker)

    table = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
        research,
        (feed,),
        (feed,),
    )["feed:target:close"]

    row = table.loc[(grid[0], "AAA")]
    assert row["available_at"] == grid[0]
    assert row["data_version"] == "aligned-v3"
    assert row["data_version_source"] == "alignment_marker.data_version"


def test_collection_preserves_full_grid_tail_values_and_late_availability() -> None:
    full_grid = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    calculation_grid = full_grid[:2]
    research = SimpleNamespace(
        targets=("AAA",),
        source_timezone="UTC",
        grid_sha256="fixture-grid-v1",
        snapshot_id="snapshot-v1",
        feed_time_kind="close_time",
        grid=pd.DataFrame(index=full_grid),
        calculation_grid=pd.DataFrame(index=calculation_grid),
    )
    frame = pd.DataFrame({"close": [10.0, 11.0, 12.0]}, index=full_grid)
    marker = {
        "grid_sha256": "fixture-grid-v1",
        "present": (True, True),
        "available_at": tuple(calculation_grid.to_pydatetime()),
        "data_version": "bars-v5",
        "full_frame": frame,
        "full_present": (True, True, True),
        "full_available_at": (
            full_grid[0].to_pydatetime(),
            (full_grid[1] + pd.Timedelta(days=1)).to_pydatetime(),
            full_grid[2].to_pydatetime(),
        ),
    }
    feed = _feed("AAA", frame.iloc[:2].copy(), marker=marker)

    table = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
        research,
        (feed,),
        (feed,),
    )["feed:target:close"]

    assert len(table) == 3
    assert table.loc[(full_grid[2], "AAA"), "value"] == 12.0
    assert table.loc[(full_grid[1], "AAA"), "available_at"] == full_grid[2]
    assert table.loc[(full_grid[1], "AAA"), "data_version"] == "bars-v5"


def test_collection_reads_real_prealign_full_frame_and_preserves_its_attrs() -> None:
    grid_index = pd.date_range("2024-03-08 21:00:00", periods=3, freq="D", tz="UTC")
    grid = pd.DataFrame(
        {"open_time": grid_index - pd.Timedelta(hours=6)},
        index=grid_index.rename("close_time"),
    )
    research = ResearchSpec(
        grid=grid,
        start=grid_index[0],
        end=grid_index[1],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="snapshot-v6",
        price_basis="USD spot close, unadjusted",
        calendar_id="fixture-calendar-v1",
        frequency="1session",
    )
    source = pd.DataFrame({"close": [10.0, 11.0, 12.0]}, index=grid_index)
    source.attrs["source_metadata"] = {
        "fields": {
            "close": {
                "name": "close",
                "semantic": "adjusted_close_price",
                "unit": "USD per share",
                "currency": "USD",
                "adjustment": "split-adjusted-v1",
            }
        }
    }
    aligned = prealign_bars(
        source,
        research,
        "AAA",
        available_at=(grid_index[0], grid_index[2], grid_index[2]),
        data_version="feed-v6",
    )

    table = collect_bound_feed_tables(
        [SimpleNamespace(field_bindings={"close": "feed:target:close"})],
        research,
        (aligned.feed,),
        (aligned.feed,),
    )["feed:target:close"]

    assert len(aligned.feed.p.dataname) == 2
    assert len(table) == 3
    assert table.loc[(grid_index[1], "AAA"), "value"] == 11.0
    assert table.loc[(grid_index[1], "AAA"), "available_at"] == grid_index[2]
    assert table.loc[(grid_index[2], "AAA"), "value"] == 12.0
    assert table.attrs["source_metadata"]["semantic"] == "adjusted_close_price"
    assert table.attrs["source_metadata"]["source_feed"] == "target"
