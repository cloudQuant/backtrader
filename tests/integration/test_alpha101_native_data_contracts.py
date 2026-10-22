"""Full-registry causal and target-order contracts on ordinary feed inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
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
    for frame in changed.values():
        frame.loc[tail, ["open", "high", "low", "close", "vwap"]] = (
            frame.loc[tail, ["open", "high", "low", "close", "vwap"]] * 1.17 + 0.31
        )
        frame.loc[tail, "volume"] = frame.loc[tail, "volume"] * 1.23 + 73.0
        frame.loc[tail, "dollar_volume"] = frame.loc[tail, "vwap"] * frame.loc[tail, "volume"]
    return changed


def _assert_asset_aligned_close(actual, expected, *, label):
    """Compare by named time/asset keys; preserve every rank-to-asset mapping."""
    aligned = actual.reindex(index=expected.index, columns=expected.columns)
    assert aligned.index.equals(expected.index), "%s time/asset index differs" % label
    assert aligned.columns.equals(expected.columns), "%s factor columns differ" % label
    np.testing.assert_allclose(
        aligned.to_numpy(dtype="float64"),
        expected.to_numpy(dtype="float64"),
        rtol=1e-10,
        atol=1e-12,
        equal_nan=True,
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
    cutoff = grid[_CUT_ROW].to_pydatetime()
    prefix_mask = study.index.get_level_values("time") < cutoff
    expected_prefix = study.loc[prefix_mask]
    reordered_prefix = reordered.get_panel().factors.loc[
        reordered.get_panel().factors.index.get_level_values("time") < cutoff
    ]
    perturbed_factors = perturbed.get_panel().factors
    perturbed_prefix = perturbed_factors.loc[
        perturbed_factors.index.get_level_values("time") < cutoff
    ]

    _assert_asset_aligned_close(reordered_prefix, expected_prefix, label="asset reorder")
    _assert_asset_aligned_close(perturbed_prefix, expected_prefix, label="future-tail perturbation")

    for alpha_id in batch:
        column = "alpha%d" % alpha_id
        assert np.isfinite(
            expected_prefix[column].to_numpy(dtype="float64")
        ).any(), "Alpha%d has no finite prefix witness in batch %d" % (alpha_id, batch_index)

    tail_time = grid[-1].to_pydatetime()
    asset = next(iter(frames))
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
