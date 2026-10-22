"""Contract tests for the plain-frame FactorPanel container."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import DatasetError, ResearchConfigError
from backtrader.research.panel import FactorPanel


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
    grid = make_grid(periods=1).iloc[0:0]
    with pytest.raises((DatasetError, ResearchConfigError, ValueError, IndexError)):
        make_panel(grid=grid)


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
