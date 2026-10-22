"""CSV round-trip contract for FactorPanel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtrader.errors import DatasetError, ResearchConfigError
from backtrader.research.panel import FactorPanel


def make_panel() -> FactorPanel:
    index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC", name="close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    targets = ("000001", "600000")
    factors = ("alpha", "beta")
    multi = pd.MultiIndex.from_product([index, targets], names=("time", "asset"))
    values = np.array(
        [
            [1.0, np.nan],
            [2.0, 20.0],
            [np.nan, 30.0],
            [4.0, 40.0],
            [5.0, 50.0],
            [6.0, 60.0],
            [7.0, 70.0],
            [8.0, 80.0],
        ]
    )
    factors_frame = pd.DataFrame(values, index=multi, columns=list(factors))
    prices = pd.DataFrame(
        np.arange(8, dtype="float64").reshape(4, 2), index=index, columns=list(targets)
    )
    universe = pd.DataFrame(True, index=index, columns=list(targets))
    universe.iloc[0, 1] = False
    return FactorPanel(
        factors=factors_frame,
        grid=grid,
        prices_open=prices,
        prices_close=prices + 0.25,
        universe=universe,
        groups={"000001": "a", "600000": "b"},
        start=index[0],
        end=index[-1],
        target_order=targets,
        factor_order=factors,
        directions={"alpha": 1, "beta": -1},
    )


def roundtrip(panel: FactorPanel, directory) -> FactorPanel:
    panel.to_csv(directory)
    return FactorPanel.from_csv(
        directory,
        start=panel.start,
        end=panel.end,
        directions=panel.directions,
        target_order=panel.target_order,
        factor_order=panel.factor_order,
        groups=panel.groups,
    )


def test_roundtrip_preserves_values_nan_and_orders(tmp_path):
    panel = make_panel()
    restored = roundtrip(panel, tmp_path / "panel")
    pd.testing.assert_frame_equal(restored.factors, panel.factors)
    pd.testing.assert_frame_equal(restored.prices_open, panel.prices_open)
    pd.testing.assert_frame_equal(restored.prices_close, panel.prices_close)
    pd.testing.assert_frame_equal(restored.universe, panel.universe)
    assert restored.target_order == panel.target_order
    assert restored.factor_order == panel.factor_order
    assert restored.directions == panel.directions
    assert restored.groups == panel.groups
    assert restored.start == panel.start
    assert restored.end == panel.end


def test_nan_cells_keep_a_row_in_the_csv(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    long = pd.read_csv(tmp_path / "panel" / "factors.csv", dtype={"asset": str})
    assert len(long) == len(panel.factors) * len(panel.factor_order)
    assert long["value"].isna().sum() == 2
    assert set(long["asset"]) == {"000001", "600000"}


def test_no_manifest_or_identity_file_is_written(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    assert sorted(path.name for path in (tmp_path / "panel").iterdir()) == [
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    ]


def test_from_csv_requires_explicit_configuration(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    with pytest.raises(ResearchConfigError):
        FactorPanel.from_csv(
            tmp_path / "panel",
            start=panel.start,
            end=panel.end,
            directions=panel.directions,
            target_order=(),
            factor_order=panel.factor_order,
        )
    with pytest.raises(ResearchConfigError):
        FactorPanel.from_csv(
            tmp_path / "panel",
            start=panel.start,
            end=panel.end,
            directions={},
            target_order=panel.target_order,
            factor_order=panel.factor_order,
        )


def test_from_csv_rejects_missing_file(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    (tmp_path / "panel" / "universe.csv").unlink()
    with pytest.raises(DatasetError):
        FactorPanel.from_csv(
            tmp_path / "panel",
            start=panel.start,
            end=panel.end,
            directions=panel.directions,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
        )


def test_from_csv_rejects_duplicate_keys(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    path = tmp_path / "panel" / "factors.csv"
    frame = pd.read_csv(path, dtype={"asset": str})
    pd.concat([frame, frame.iloc[[0]]]).to_csv(path, index=False)
    with pytest.raises(DatasetError):
        FactorPanel.from_csv(
            tmp_path / "panel",
            start=panel.start,
            end=panel.end,
            directions=panel.directions,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
        )


def test_from_csv_rejects_truncated_factor_rows(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    path = tmp_path / "panel" / "factors.csv"
    frame = pd.read_csv(path, dtype={"asset": str})
    frame[frame["factor"] != "beta"].to_csv(path, index=False)
    with pytest.raises(DatasetError):
        FactorPanel.from_csv(
            tmp_path / "panel",
            start=panel.start,
            end=panel.end,
            directions=panel.directions,
            target_order=panel.target_order,
            factor_order=panel.factor_order,
        )


def test_to_csv_refuses_to_overwrite_an_existing_directory(tmp_path):
    panel = make_panel()
    panel.to_csv(tmp_path / "panel")
    with pytest.raises(DatasetError):
        panel.to_csv(tmp_path / "panel")


def test_to_csv_refuses_to_replace_a_dangling_symlink(tmp_path):
    panel = make_panel()
    target = tmp_path / "panel"
    try:
        target.symlink_to(tmp_path / "missing", target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(DatasetError, match="already exists"):
        panel.to_csv(target)
    assert target.is_symlink()


def test_asset_ids_with_leading_zeros_survive_csv(tmp_path):
    restored = roundtrip(make_panel(), tmp_path / "panel")
    assert restored.target_order == ("000001", "600000")
    assert restored.factors.index.get_level_values("asset")[0] == "000001"


def test_float_values_round_trip_bit_exactly(tmp_path):
    tricky = [0.1 + 0.2, 1.0 / 3.0, 123456789.123456789, 2.220446049250313e-16]
    grid = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC", name="close_time")
    grid_frame = pd.DataFrame({"open_time": grid - pd.Timedelta(hours=6)}, index=grid)
    index = pd.MultiIndex.from_product([grid, ("A",)], names=("time", "asset"))
    frame = pd.DataFrame({"f": tricky[:2]}, index=index)
    prices = pd.DataFrame({"A": tricky[:2]}, index=grid)
    panel = FactorPanel(
        factors=frame,
        grid=grid_frame,
        prices_open=prices,
        prices_close=prices,
        start=grid[0],
        end=grid[-1],
        target_order=("A",),
        factor_order=("f",),
        directions={"f": 1},
    )
    panel.to_csv(tmp_path / "panel")
    restored = FactorPanel.from_csv(
        tmp_path / "panel",
        start=grid[0],
        end=grid[-1],
        directions={"f": 1},
        target_order=("A",),
        factor_order=("f",),
    )
    assert [repr(float(v)) for v in restored.factors["f"]] == [
        repr(float(v)) for v in frame["f"]
    ]
    assert [repr(float(v)) for v in restored.prices_open["A"]] == [
        repr(float(v)) for v in prices["A"]
    ]
