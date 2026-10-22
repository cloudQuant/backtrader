"""Full-registry causal and target-order contracts on ordinary feed inputs."""

from __future__ import annotations

import numpy as np
import pytest

from tests.test_utils.alpha101_full_reference import formula_ids
from tests.test_utils.alpha101_native_harness import make_positive_fixture, run_native_batch

_HISTORY = 320
_ASSET_COUNT = 6
_BATCH_SIZE = 20
_CUT_ROW = 280
_RUN_MODES = (False, True)  # runnext, runonce


def _batches():
    ids = tuple(formula_ids())
    return tuple(ids[index : index + _BATCH_SIZE] for index in range(0, len(ids), _BATCH_SIZE))


def _mutate_future_tail(frames, grid):
    """Change future prices and volume, then rebuild the source dollar volume."""
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    tail = list(grid[_CUT_ROW:])
    for asset_index, frame in enumerate(changed.values()):
        price_scale = 1.17 + asset_index * 0.07
        price_offset = 0.31 + asset_index * 0.11
        frame.loc[tail, ["open", "high", "low", "close", "vwap"]] = (
            frame.loc[tail, ["open", "high", "low", "close", "vwap"]] * price_scale + price_offset
        )
        frame.loc[tail, "volume"] = (
            frame.loc[tail, "volume"] * (1.23 + asset_index * 0.05) + 73.0 + asset_index
        )
        frame.loc[tail, "dollar_volume"] = frame.loc[tail, "vwap"] * frame.loc[tail, "volume"]
    return changed


def _panel_tensor(panel, assets, expected_times, *, label):
    """Read a panel in observed time order, restoring only asset identity."""
    assert tuple(panel.index.names) == ("time", "asset"), "%s panel index changed" % label
    factor_names = tuple(panel.columns)
    observed_times = tuple(dict.fromkeys(panel.index.get_level_values("time")))
    assert observed_times == tuple(expected_times), "%s time order differs" % label

    rows = []
    expected_assets = set(assets)
    for point in observed_times:
        by_asset = panel.xs(point, level="time")
        assert not by_asset.index.has_duplicates, "%s has duplicate asset rows at %s" % (
            label,
            point,
        )
        assert set(by_asset.index) == expected_assets, "%s asset identity set differs at %s" % (
            label,
            point,
        )
        rows.append(by_asset.reindex(list(assets)).to_numpy(dtype="float64"))
    return np.stack(rows, axis=0), factor_names


def _assert_panel_tensor_close(actual, expected, *, label):
    """Compare every cell, requiring the finite/NaN mask to match exactly."""
    assert actual.shape == expected.shape, "%s panel dimensions differ" % label
    actual_finite = np.isfinite(actual)
    expected_finite = np.isfinite(expected)
    np.testing.assert_array_equal(actual_finite, expected_finite, err_msg=label + " finite mask")
    assert not np.isinf(actual).any(), "%s contains an infinite actual value" % label
    assert not np.isinf(expected).any(), "%s contains an infinite expected value" % label
    np.testing.assert_allclose(
        actual[actual_finite],
        expected[expected_finite],
        rtol=1e-10,
        atol=1e-12,
        err_msg=label,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "batch_index",
    range(len(_batches())),
    ids=lambda value: "batch-%d" % value,
)
@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_all_alpha101_batches_are_asset_order_invariant_and_causal(batch_index, runonce):
    batch = _batches()[batch_index]
    frames = make_positive_fixture(_HISTORY)
    assert len(frames) == _ASSET_COUNT
    grid = tuple(next(iter(frames.values())).index)
    assert len(grid) == _HISTORY

    baseline = run_native_batch(frames, batch, runonce=runonce)
    reversed_frames = dict(reversed(tuple(frames.items())))
    reordered = run_native_batch(reversed_frames, batch, runonce=runonce)
    perturbed_frames = _mutate_future_tail(frames, grid)
    perturbed = run_native_batch(perturbed_frames, batch, runonce=runonce)

    study = baseline.get_panel().factors
    baseline_values, factor_names = _panel_tensor(study, tuple(frames), grid, label="baseline")
    reordered_values, reordered_names = _panel_tensor(
        reordered.get_panel().factors, tuple(frames), grid, label="reordered"
    )
    perturbed_values, perturbed_names = _panel_tensor(
        perturbed.get_panel().factors, tuple(frames), grid, label="perturbed"
    )
    assert reordered_names == factor_names == perturbed_names

    # The time axis stays in the observed order. Only asset identities are
    # restored within each time slice before comparing the complete panel.
    _assert_panel_tensor_close(reordered_values, baseline_values, label="full asset reorder")
    np.testing.assert_array_equal(
        perturbed_values[:_CUT_ROW],
        baseline_values[:_CUT_ROW],
        err_msg="future-tail prefix",
    )

    for alpha_id in batch:
        column = "alpha%d" % alpha_id
        assert column in factor_names
        factor_index = factor_names.index(column)
        assert np.isfinite(
            baseline_values[:_CUT_ROW, :, factor_index]
        ).any(), "Alpha%d has no finite prefix witness in batch %d" % (alpha_id, batch_index)

    # Prove that the source mutation reached real formula inputs, then that
    # the aligned panel retained the changed close input on the perturbed tail.
    asset = next(iter(frames))
    original_tail = frames[asset].loc[grid[-1], ["open", "close", "vwap", "volume"]]
    changed_tail = perturbed_frames[asset].loc[grid[-1], ["open", "close", "vwap", "volume"]]
    assert not original_tail.equals(changed_tail), "future input mutation was a no-op"
    tail_time = grid[-1].to_pydatetime()
    assert (
        perturbed.get_panel().prices_close.at[tail_time, asset]
        != baseline.get_panel().prices_close.at[tail_time, asset]
    )
    for frame in perturbed_frames.values():
        np.testing.assert_allclose(
            frame["dollar_volume"].to_numpy(dtype="float64"),
            (frame["vwap"] * frame["volume"]).to_numpy(dtype="float64"),
            rtol=0.0,
            atol=0.0,
        )
