"""R71-166 regression coverage for independent Sharpe trial counts."""

import math

import pandas as pd
import pytest

from backtrader.analyzers.sharpe_ratio_stats import (
    expected_maximum_sr,
    num_independent_trials,
)


def _independent_count_reference(m, p):
    """Apply the effective-trial formula and its documented count bounds."""
    effective_count = p + (1.0 - p) * m
    return min(m, max(1, math.ceil(effective_count)))


@pytest.mark.parametrize(
    ("m", "p"),
    (
        (1, -1.0),
        (1, 0.0),
        (1, 0.75),
        (1, 1.0),
        (5, -1.0),
        (5, -0.5),
        (5, 0.0),
        (5, 0.3),
        (5, 0.5),
        (5, 1.0),
        (6, 0.2),
    ),
)
def test_num_independent_trials_matches_bounded_ceil_reference(m, p):
    expected = _independent_count_reference(m, p)

    assert 1 <= expected <= m
    assert num_independent_trials(m=m, p=p) == expected


def test_single_trial_frame_has_one_independent_trial_and_expected_maximum():
    trials_returns = pd.DataFrame(
        {"only": [-0.02, 0.01, 0.03, -0.01, 0.02]}
    )
    expected_count = _independent_count_reference(1, 0.0)

    assert num_independent_trials(trials_returns=trials_returns) == expected_count
    assert expected_maximum_sr(
        trials_returns=trials_returns,
        expected_mean_sr=0.25,
    ) == pytest.approx(0.25)


def test_num_independent_trials_rejects_zero_column_frame():
    trials_returns = pd.DataFrame(index=range(5))

    with pytest.raises(ValueError, match="num_independent_trials requires m > 0"):
        num_independent_trials(trials_returns=trials_returns)


def test_expected_maximum_sr_rejects_zero_column_frame_trial_count():
    trials_returns = pd.DataFrame(index=range(5))

    with pytest.raises(ValueError, match="num_independent_trials requires m > 0"):
        expected_maximum_sr(trials_returns=trials_returns)
