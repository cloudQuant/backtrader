"""Contract tests for the plain-frame FactorPanel container."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import DatasetError, ResearchConfigError
from backtrader.research.panel import FactorPanel, _astype_frame, _shallow_copy_frame


def make_grid(periods: int = 4, tz: str = "UTC") -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="D", tz=tz, name="close_time")
    return pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)


def make_panel(**overrides):
    grid = overrides.pop("grid", make_grid())
    targets = overrides.pop("targets", ("000001", "600000"))
    factors = overrides.pop("factor_order", ("alpha", "beta"))
    directions = overrides.pop("directions", {name: 1 for name in factors})
    start = overrides.pop("start", grid.index[0])
    end = overrides.pop("end", grid.index[-1])
    index = pd.MultiIndex.from_product(
        [grid.index, targets], names=("time", "asset")
    )
    values = np.arange(len(index) * len(factors), dtype="float64").reshape(
        len(index), len(factors)
    )
    factors_frame = pd.DataFrame(values, index=index, columns=list(factors))
    prices = pd.DataFrame(
        np.arange(len(grid) * len(targets), dtype="float64").reshape(len(grid), len(targets)),
        index=grid.index,
        columns=list(targets),
    )
    kwargs = dict(
        factors=factors_frame,
        grid=grid,
        prices_open=prices,
        prices_close=prices + 1.0,
        start=start,
        end=end,
        target_order=targets,
        factor_order=factors,
        directions=directions,
    )
    kwargs.update(overrides)
    return FactorPanel(**kwargs)


def test_panel_keeps_declared_order_and_shapes():
    panel = make_panel()
    assert tuple(panel.factor_order) == ("alpha", "beta")
    assert tuple(panel.target_order) == ("000001", "600000")
    assert tuple(panel.factors.columns) == ("alpha", "beta")
    assert panel.factors.index.names == ["time", "asset"]
    assert panel.start == panel.grid.index[0]
    assert panel.end == panel.grid.index[-1]
    assert panel.universe.shape == (4, 2)
    assert bool(panel.universe.to_numpy().all())
    assert panel.groups == {"000001": "default", "600000": "default"}
    assert panel.directions == {"alpha": 1, "beta": 1}
    assert panel.factor_values("beta").name == "beta"
    assert panel.price("open") is panel.prices_open
    assert panel.study_factors() is panel.factors


def test_asset_ids_stay_strings_and_leading_zeros_survive():
    panel = make_panel(targets=("000001", "600000"))
    assert panel.target_order == ("000001", "600000")
    assert all(isinstance(value, str) for value in panel.target_order)


def test_all_nan_factor_is_kept_not_dropped_or_filled():
    panel = make_panel()
    panel.factors["alpha"] = np.nan
    rebuilt = FactorPanel(
        factors=panel.factors,
        grid=panel.grid,
        prices_open=panel.prices_open,
        prices_close=panel.prices_close,
        start=panel.start,
        end=panel.end,
        target_order=panel.target_order,
        factor_order=panel.factor_order,
        directions=panel.directions,
    )
    assert rebuilt.factors["alpha"].isna().all()
    assert len(rebuilt.factors) == 4 * 2


def test_factor_grid_must_cover_calculation_grid_and_targets():
    panel = make_panel()
    truncated = panel.factors.iloc[:-1]
    with pytest.raises(DatasetError):
        FactorPanel(
            factors=truncated,
            grid=panel.grid,
            prices_open=panel.prices_open,
            prices_close=panel.prices_close,
            start=panel.start,
            end=panel.end,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
            directions=panel.directions,
        )


def test_warmup_rows_before_start_are_not_part_of_the_factor_index():
    grid = make_grid(periods=6)
    start = grid.index[2]
    with pytest.raises(DatasetError):
        make_panel(grid=grid, start=start, end=grid.index[-1])
    index = pd.MultiIndex.from_product(
        [grid.index[2:], ("000001", "600000")], names=("time", "asset")
    )
    frame = pd.DataFrame(
        np.arange(len(index) * 2, dtype="float64").reshape(len(index), 2),
        index=index,
        columns=["alpha", "beta"],
    )
    prices = pd.DataFrame(1.0, index=grid.index, columns=["000001", "600000"])
    panel = FactorPanel(
        factors=frame,
        grid=grid,
        prices_open=prices,
        prices_close=prices,
        start=start,
        end=grid.index[-1],
        target_order=("000001", "600000"),
        factor_order=("alpha", "beta"),
        directions={"alpha": 1, "beta": 1},
    )
    assert len(panel.factors) == 4 * 2
    assert panel.universe.shape == (4, 2)
    assert panel.universe.index[0] == start
    assert panel.prices_open.shape[0] == 6


def test_directions_must_cover_every_factor_with_plus_or_minus_one():
    with pytest.raises(ResearchConfigError):
        make_panel(directions={"alpha": 1})
    with pytest.raises(ResearchConfigError):
        make_panel(directions={"alpha": 1, "beta": 0})
    with pytest.raises(ResearchConfigError):
        make_panel(directions={"alpha": 1, "beta": 1, "gamma": 1})


def test_empty_grid_targets_and_factors_are_rejected():
    with pytest.raises((DatasetError, ResearchConfigError, ValueError)):
        make_panel(targets=())
    with pytest.raises((DatasetError, ResearchConfigError, ValueError)):
        make_panel(factor_order=())
    panel = make_panel()
    grid = panel.grid.iloc[0:0]
    with pytest.raises(ResearchConfigError, match="grid must not be empty"):
        FactorPanel(
            factors=panel.factors,
            grid=grid,
            prices_open=panel.prices_open,
            prices_close=panel.prices_close,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
            directions=panel.directions,
        )


def test_duplicate_factor_columns_are_rejected():
    panel = make_panel()
    factors = panel.factors.copy(deep=True)
    factors.columns = ["alpha", "alpha"]
    with pytest.raises(ResearchConfigError, match="factor columns must be unique"):
        FactorPanel(
            factors=factors,
            grid=panel.grid,
            prices_open=panel.prices_open,
            prices_close=panel.prices_close,
            start=panel.start,
            end=panel.end,
            target_order=panel.target_order,
            factor_order=("alpha", "alpha"),
            directions={"alpha": 1},
        )


@pytest.mark.parametrize(
    "values",
    [
        [0, 1, 0, 1],
        ["False", "True", "False", "True"],
    ],
    ids=["numeric-column", "string-column"],
)
def test_universe_requires_boolean_dtype_for_every_column(values):
    panel = make_panel()
    universe = pd.DataFrame(
        {"000001": [True] * len(panel.universe), "600000": values},
        index=panel.universe.index,
    )
    with pytest.raises(DatasetError, match="non-missing boolean values"):
        FactorPanel(
            factors=panel.factors,
            grid=panel.grid,
            prices_open=panel.prices_open,
            prices_close=panel.prices_close,
            universe=universe,
            start=panel.start,
            end=panel.end,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
            directions=panel.directions,
        )


def test_panel_validation_does_not_mutate_caller_frames():
    panel = make_panel()
    universe = panel.universe.copy(deep=True)
    universe.columns.name = "caller metadata"
    inputs = {
        "factors": panel.factors,
        "grid": panel.grid,
        "prices_open": panel.prices_open,
        "prices_close": panel.prices_close,
        "universe": universe,
    }
    before = {name: frame.copy(deep=True) for name, frame in inputs.items()}
    FactorPanel(
        factors=inputs["factors"],
        grid=inputs["grid"],
        prices_open=inputs["prices_open"],
        prices_close=inputs["prices_close"],
        universe=inputs["universe"],
        start=panel.start,
        end=panel.end,
        target_order=panel.target_order,
        factor_order=panel.factor_order,
        directions=panel.directions,
    )
    for name, frame in inputs.items():
        pd.testing.assert_frame_equal(frame, before[name])


def test_panel_borrows_canonical_values_and_owns_normalized_metadata():
    grid = make_grid(periods=3)
    targets = ("000001", "600000")
    factor_index = pd.MultiIndex.from_product([grid.index, targets], names=("time", "asset"))
    factors = pd.DataFrame(
        np.arange(len(factor_index) * 2, dtype="float64").reshape(-1, 2),
        index=factor_index,
        columns=pd.Index(("alpha", "beta"), name="caller_factor_columns"),
    )
    price_values = np.arange(len(grid) * len(targets), dtype="float64").reshape(
        len(grid), len(targets)
    )
    prices_open = pd.DataFrame(
        price_values,
        index=grid.index,
        columns=pd.Index(targets, name="caller_price_columns"),
    )
    prices_close = pd.DataFrame(
        price_values + 1.0,
        index=grid.index,
        columns=pd.Index(targets, name="caller_price_columns"),
    )
    universe = pd.DataFrame(
        np.ones((len(grid), len(targets)), dtype=bool),
        index=grid.index,
        columns=pd.Index(targets, name="caller_universe_columns"),
    )
    inputs = {
        "factors": factors,
        "grid": grid,
        "prices_open": prices_open,
        "prices_close": prices_close,
        "universe": universe,
    }
    for name, frame in inputs.items():
        frame.attrs["ownership"] = {"label": name}

    panel = FactorPanel(
        factors=factors,
        grid=grid,
        prices_open=prices_open,
        prices_close=prices_close,
        universe=universe,
        start=grid.index[0],
        end=grid.index[-1],
        target_order=targets,
        factor_order=("alpha", "beta"),
        directions={"alpha": 1, "beta": -1},
    )

    for name in ("factors", "prices_open", "prices_close", "universe"):
        source = inputs[name]
        normalized = getattr(panel, name)
        assert np.shares_memory(source.to_numpy(copy=False), normalized.to_numpy(copy=False))
        assert normalized is not source
        assert normalized.index is not source.index
        assert normalized.columns is not source.columns
        assert normalized.attrs is not source.attrs
        assert normalized.attrs["ownership"] is not source.attrs["ownership"]

    assert panel.grid.index is not grid.index
    assert panel.grid.columns is not grid.columns
    assert panel.grid.attrs is not grid.attrs
    assert panel.grid.attrs["ownership"] is not grid.attrs["ownership"]
    assert np.shares_memory(grid["open_time"].array.asi8, panel.grid["open_time"].array.asi8)
    assert panel.grid.index.freq is None
    assert grid.index.freq == pd.offsets.Day()
    assert panel.factors.index.levels[0].freq is None
    assert factors.index.levels[0].freq == pd.offsets.Day()
    assert panel.universe.columns.name is None

    panel.grid.index.name = "panel_close_time"
    panel.grid.columns.name = "panel_grid_columns"
    panel.factors.columns.name = "panel_factor_columns"
    panel.universe.columns.name = "panel_universe_columns"
    for name in inputs:
        getattr(panel, name).attrs["ownership"]["label"] = "panel"

    assert grid.index.name == "close_time"
    assert grid.columns.name is None
    assert factors.columns.name == "caller_factor_columns"
    assert universe.columns.name == "caller_universe_columns"
    assert grid.attrs["ownership"] == {"label": "grid"}
    assert factors.attrs["ownership"] == {"label": "factors"}
    assert prices_open.attrs["ownership"] == {"label": "prices_open"}
    assert prices_close.attrs["ownership"] == {"label": "prices_close"}
    assert universe.attrs["ownership"] == {"label": "universe"}


def test_shallow_frame_copy_isolates_nested_attrs_when_copy_only_shallow_copies_them(
    monkeypatch,
):
    frame = pd.DataFrame({"value": [1.0]})
    frame.attrs["owner"] = {"labels": ["caller"]}
    original_copy = pd.DataFrame.copy

    def shallow_attrs_copy(self, deep=True):
        result = original_copy(self, deep=deep)
        if not deep:
            result.attrs = self.attrs.copy()
        return result

    monkeypatch.setattr(pd.DataFrame, "copy", shallow_attrs_copy)
    normalized = _shallow_copy_frame(frame)

    assert normalized.attrs is not frame.attrs
    assert normalized.attrs["owner"] is not frame.attrs["owner"]
    assert normalized.attrs["owner"]["labels"] is not frame.attrs["owner"]["labels"]
    normalized.attrs["owner"]["labels"].append("panel")
    assert frame.attrs["owner"]["labels"] == ["caller"]


def test_dtype_conversion_tolerates_missing_copy_on_write_option(monkeypatch):
    frame = pd.DataFrame({"value": np.array([1, 2], dtype="int64")})
    original_get_option = pd.get_option

    def get_option(name):
        if name == "mode.copy_on_write":
            raise AttributeError("option is unavailable on this pandas version")
        return original_get_option(name)

    monkeypatch.setattr(pd, "get_option", get_option)
    converted = _astype_frame(frame, "float64", pd)

    assert converted["value"].dtype == np.dtype("float64")
    np.testing.assert_array_equal(converted["value"], np.array([1.0, 2.0]))


def test_panel_converts_only_noncanonical_frame_dtypes():
    grid = make_grid(periods=2)
    targets = ("A", "B")
    index = pd.MultiIndex.from_product([grid.index, targets], names=("time", "asset"))
    canonical_factor = np.arange(len(index), dtype="float64")
    converted_factor = np.arange(len(index), dtype="int64") + 10
    factors = pd.DataFrame(
        {"canonical": canonical_factor, "converted": converted_factor}, index=index
    )
    open_values = np.arange(len(grid) * len(targets), dtype="float32").reshape(
        len(grid), len(targets)
    )
    prices_open = pd.DataFrame(open_values, index=grid.index, columns=list(targets))
    prices_close = pd.DataFrame(
        np.arange(len(grid) * len(targets), dtype="int64").reshape(len(grid), len(targets)),
        index=grid.index,
        columns=list(targets),
    )
    universe = pd.DataFrame(
        {
            "A": pd.array([True, False], dtype="boolean"),
            "B": pd.array([False, True], dtype="boolean"),
        },
        index=grid.index,
    )

    panel = FactorPanel(
        factors=factors,
        grid=grid,
        prices_open=prices_open,
        prices_close=prices_close,
        universe=universe,
        start=grid.index[0],
        end=grid.index[-1],
        target_order=targets,
        factor_order=("canonical", "converted"),
        directions={"canonical": 1, "converted": -1},
    )

    assert panel.factors["canonical"].dtype == np.dtype("float64")
    assert panel.factors["converted"].dtype == np.dtype("float64")
    assert np.shares_memory(
        factors["canonical"].to_numpy(copy=False),
        panel.factors["canonical"].to_numpy(copy=False),
    )
    assert not np.shares_memory(
        factors["converted"].to_numpy(copy=False),
        panel.factors["converted"].to_numpy(copy=False),
    )
    assert panel.prices_open.dtypes.tolist() == [np.dtype("float64")] * len(targets)
    assert panel.prices_close.dtypes.tolist() == [np.dtype("float64")] * len(targets)
    assert not np.shares_memory(
        prices_open.to_numpy(copy=False), panel.prices_open.to_numpy(copy=False)
    )
    assert not np.shares_memory(
        prices_close.to_numpy(copy=False), panel.prices_close.to_numpy(copy=False)
    )
    assert panel.universe.dtypes.tolist() == [np.dtype("bool")] * len(targets)
    assert panel.universe.to_numpy().tolist() == [[True, False], [False, True]]
    np.testing.assert_array_equal(panel.factors["converted"], converted_factor.astype("float64"))
    np.testing.assert_array_equal(panel.prices_open.to_numpy(), open_values.astype("float64"))


def test_infinite_values_are_rejected_but_nan_is_allowed():
    panel = make_panel()
    broken = panel.factors.copy()
    broken.iloc[0, 0] = np.inf
    with pytest.raises(DatasetError):
        FactorPanel(
            factors=broken,
            grid=panel.grid,
            prices_open=panel.prices_open,
            prices_close=panel.prices_close,
            start=panel.start,
            end=panel.end,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
            directions=panel.directions,
        )


def test_supplied_universe_is_not_silently_widened():
    panel = make_panel()
    universe = panel.universe.copy()
    universe.iloc[0, 0] = False
    rebuilt = FactorPanel(
        factors=panel.factors,
        grid=panel.grid,
        prices_open=panel.prices_open,
        prices_close=panel.prices_close,
        universe=universe,
        start=panel.start,
        end=panel.end,
        target_order=panel.target_order,
        factor_order=panel.factor_order,
        directions=panel.directions,
    )
    assert not bool(rebuilt.universe.iloc[0, 0])
    assert int(rebuilt.universe.to_numpy().sum()) == 7


def test_panel_is_a_plain_container_not_a_frozen_snapshot():
    panel = make_panel()
    panel.factors.iloc[0, 0] = 123.0
    assert panel.factors.iloc[0, 0] == 123.0
    assert not hasattr(panel, "dataset_id")
