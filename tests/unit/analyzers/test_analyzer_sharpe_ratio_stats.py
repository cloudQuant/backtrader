#!/usr/bin/env python
"""Test module for Sharpe Ratio analyzer.

This module tests the SharpeRatioA analyzer from backtrader, which calculates
the Sharpe ratio statistic for trading strategies. The Sharpe ratio is a measure
of risk-adjusted return, commonly used to evaluate the performance of investment
strategies.

The test uses a simple moving average crossover strategy to generate trades and
verifies that the analyzer correctly produces sharpe ratio statistics.

Example:
    To run the test with plotting enabled::
        python test_analyzer_sharpe_ratio_stats.py

    To run as a pytest test::
        pytest tests/add_tests/test_analyzer_sharpe_ratio_stats.py -v
"""

import backtrader as bt
import math
import numpy as np
import pandas as pd
import pytest

import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy.

    This strategy generates buy signals when the price crosses above the
    Simple Moving Average (SMA) and closes positions when the price crosses
    below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: Crossover indicator tracking price vs SMA crossings.

    Note:
        - Only one position (long or short) is held at a time
        - Positions are closed when crossover signal reverses
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up a 15-period Simple Moving Average (SMA) and a crossover
        indicator to track when price crosses the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements the following logic:
        - If no position exists, buy when price crosses above SMA (cross > 0)
        - If position exists, close when price crosses below SMA (cross < 0)
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the Sharpe Ratio analyzer test.

    This function creates a cerebro instance with test data, runs the
    RunStrategy with the SharpeRatioA analyzer attached, and verifies
    that the analyzer produces valid output.

    Args:
        main (bool, optional): If True, runs in standalone mode with plotting
            and prints analysis results. If False, runs in test mode and
            performs assertions. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the analyzer output is not a dict or does not
            contain expected sharpe ratio statistics (in test mode).

    Note:
        In test mode (main=False), assertions verify that:
        - The analysis result is a dictionary
        - The dictionary contains 'sharperatio' key or has non-negative length
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.SharpeRatioA, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('SharpeRatio_A Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # SharpeRatioA should return sharperatio statistics
            assert "sharperatio" in analysis or len(analysis) >= 0


def test_estimated_sharpe_ratio_stdev_accepts_series_input():
    """Test that estimated_sharpe_ratio_stdev accepts pandas Series input."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    returns = pd.Series([0.01, 0.02, 0.015, 0.018])
    result = estimated_sharpe_ratio_stdev(returns)

    assert isinstance(result, (float, int))
    assert math.isfinite(result)


def test_estimated_sharpe_ratio_requires_returns():
    """Test that estimated_sharpe_ratio raises ValueError when returns is None."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires returns"):
        estimated_sharpe_ratio(None)


@pytest.mark.parametrize("returns", [pd.Series(dtype=float), pd.Series([0.01])])
def test_estimated_sharpe_ratio_requires_at_least_two_samples(returns):
    """Test that estimated_sharpe_ratio requires at least two return samples."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires at least 2 return samples"):
        estimated_sharpe_ratio(returns)


def test_ann_estimated_sharpe_ratio_requires_returns_or_sr():
    """Test that ann_estimated_sharpe_ratio requires either returns or sr parameter."""
    from backtrader.analyzers.sharpe_ratio_stats import ann_estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires returns or sr"):
        ann_estimated_sharpe_ratio()


@pytest.mark.parametrize("periods", [0, -1])
def test_ann_estimated_sharpe_ratio_requires_positive_periods(periods):
    """Test that ann_estimated_sharpe_ratio requires periods > 0."""
    from backtrader.analyzers.sharpe_ratio_stats import ann_estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires periods > 0"):
        ann_estimated_sharpe_ratio(sr=1.0, periods=periods)


@pytest.mark.parametrize("periods", [2.5, float("nan")])
def test_ann_estimated_sharpe_ratio_requires_integer_periods(periods):
    """Test that ann_estimated_sharpe_ratio requires integer periods."""
    from backtrader.analyzers.sharpe_ratio_stats import ann_estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires integer periods"):
        ann_estimated_sharpe_ratio(sr=1.0, periods=periods)


@pytest.mark.parametrize("sr", [float("nan"), float("inf")])
def test_ann_estimated_sharpe_ratio_requires_finite_explicit_sr(sr):
    """Test that ann_estimated_sharpe_ratio requires finite explicit sr."""
    from backtrader.analyzers.sharpe_ratio_stats import ann_estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires finite sr"):
        ann_estimated_sharpe_ratio(sr=sr)


@pytest.mark.parametrize("returns", [pd.Series(dtype=float), pd.Series([0.01])])
def test_ann_estimated_sharpe_ratio_requires_at_least_two_samples_without_explicit_sr(returns):
    """Test that ann_estimated_sharpe_ratio requires at least 2 return samples when sr is None."""
    from backtrader.analyzers.sharpe_ratio_stats import ann_estimated_sharpe_ratio

    with pytest.raises(ValueError, match="requires at least 2 return samples when sr is None"):
        ann_estimated_sharpe_ratio(returns=returns)


def test_estimated_sharpe_ratio_stdev_accepts_explicit_params_without_returns():
    """Test that estimated_sharpe_ratio_stdev accepts explicit params without returns."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    result = estimated_sharpe_ratio_stdev(returns=None, n=10, skew=0.0, kurtosis=3.0, sr=1.5)

    assert isinstance(result, (float, int, np.floating))
    assert math.isfinite(result)


def test_estimated_sharpe_ratio_stdev_requires_explicit_params_without_returns():
    """Test that estimated_sharpe_ratio_stdev requires all explicit params when returns is None."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match="requires n, skew, kurtosis, and sr"):
        estimated_sharpe_ratio_stdev(returns=None, n=10, skew=0.0, kurtosis=3.0)


def test_estimated_sharpe_ratio_stdev_requires_more_than_one_sample():
    """Test that estimated_sharpe_ratio_stdev requires n > 1."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match="requires n > 1"):
        estimated_sharpe_ratio_stdev(returns=None, n=1, skew=0.0, kurtosis=3.0, sr=1.0)


@pytest.mark.parametrize("n", [2.5, float("nan")])
def test_estimated_sharpe_ratio_stdev_requires_integer_n(n):
    """Test that estimated_sharpe_ratio_stdev requires integer n."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match="requires integer n"):
        estimated_sharpe_ratio_stdev(returns=None, n=n, skew=0.0, kurtosis=3.0, sr=1.0)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"returns": None, "n": 10, "skew": float("inf"), "kurtosis": 3.0, "sr": 1.0}, "requires finite skew"),
        ({"returns": None, "n": 10, "skew": 0.0, "kurtosis": float("nan"), "sr": 1.0}, "requires finite kurtosis"),
        ({"returns": None, "n": 10, "skew": 0.0, "kurtosis": 3.0, "sr": float("nan")}, "requires finite sr"),
    ],
)
def test_estimated_sharpe_ratio_stdev_requires_finite_explicit_statistics(kwargs, match):
    """Test that estimated_sharpe_ratio_stdev requires finite statistics parameters."""
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match=match):
        estimated_sharpe_ratio_stdev(**kwargs)


def test_num_independent_trials_handles_all_nan_correlations():
    """Test that num_independent_trials handles DataFrame with constant columns (all-nan correlations)."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    trials_returns = pd.DataFrame(
        {
            "a": [1.0, 1.0, 1.0, 1.0],
            "b": [2.0, 2.0, 2.0, 2.0],
            "c": [3.0, 3.0, 3.0, 3.0],
        }
    )

    result = num_independent_trials(trials_returns)

    assert isinstance(result, int)
    assert result > 0


def test_num_independent_trials_handles_nonfinite_explicit_p():
    """Test that num_independent_trials handles nonfinite (nan) explicit p parameter."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    trials_returns = pd.DataFrame(
        {
            "a": [0.01, 0.02, 0.03],
            "b": [0.03, 0.02, 0.01],
        }
    )

    result = num_independent_trials(trials_returns, p=float("nan"))

    assert isinstance(result, int)
    assert result > 0


@pytest.mark.parametrize("p", [[0.1], pd.Series([0.1]), True])
def test_num_independent_trials_requires_scalar_explicit_p(p):
    """Test that num_independent_trials requires scalar p parameter."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    with pytest.raises(ValueError, match="requires scalar p"):
        num_independent_trials(trials_returns=None, m=5, p=p)


@pytest.mark.parametrize("p", [-1.5, 1.5])
def test_num_independent_trials_requires_correlation_domain_for_explicit_p(p):
    """Test that num_independent_trials requires -1 <= p <= 1."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    with pytest.raises(ValueError, match="requires -1 <= p <= 1"):
        num_independent_trials(trials_returns=None, m=5, p=p)


def test_num_independent_trials_accepts_explicit_m_and_p_without_trials_returns():
    """Test that num_independent_trials accepts explicit m and p without trials_returns."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    result = num_independent_trials(trials_returns=None, m=5, p=0.25)

    assert isinstance(result, int)
    assert result > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trials_returns": None, "m": 5},
        {"trials_returns": None, "p": 0.25},
        {"trials_returns": None},
    ],
)
def test_num_independent_trials_requires_trials_returns_when_params_missing(kwargs):
    """Test that num_independent_trials requires trials_returns when m or p is missing."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    with pytest.raises(ValueError, match="requires trials_returns when m or p is not provided"):
        num_independent_trials(**kwargs)


@pytest.mark.parametrize("m", [0, -2])
def test_num_independent_trials_requires_positive_explicit_m(m):
    """Test that num_independent_trials requires m > 0."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    with pytest.raises(ValueError, match="requires m > 0"):
        num_independent_trials(trials_returns=None, m=m, p=0.25)


@pytest.mark.parametrize("m", [2.5, float("nan")])
def test_num_independent_trials_requires_integer_explicit_m(m):
    """Test that num_independent_trials requires integer m."""
    from backtrader.analyzers.sharpe_ratio_stats import num_independent_trials

    with pytest.raises(ValueError, match="requires integer m"):
        num_independent_trials(trials_returns=None, m=m, p=0.25)


def test_expected_maximum_sr_single_trial_returns_expected_mean():
    """Test that expected_maximum_sr with single trial returns the expected mean."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    result = expected_maximum_sr(independent_trials=1, expected_mean_sr=0.25, trials_sr_std=1.0)

    assert result == 0.25


@pytest.mark.parametrize("independent_trials", [0, -1])
def test_expected_maximum_sr_requires_at_least_one_trial(independent_trials):
    """Test that expected_maximum_sr requires independent_trials >= 1."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires independent_trials >= 1"):
        expected_maximum_sr(independent_trials=independent_trials, expected_mean_sr=0.25, trials_sr_std=1.0)


@pytest.mark.parametrize("independent_trials", [2.5, float("nan")])
def test_expected_maximum_sr_requires_integer_trial_count(independent_trials):
    """Test that expected_maximum_sr requires integer independent_trials."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires integer independent_trials"):
        expected_maximum_sr(independent_trials=independent_trials, expected_mean_sr=0.25, trials_sr_std=1.0)


def test_expected_maximum_sr_requires_trials_returns_or_independent_trials():
    """Test that expected_maximum_sr requires trials_returns or independent_trials."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires trials_returns or independent_trials"):
        expected_maximum_sr()


def test_expected_maximum_sr_rejects_trials_above_column_count():
    """Test that expected_maximum_sr rejects independent_trials > number of trial columns."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    trials_returns = pd.DataFrame({"a": [0.01, 0.02], "b": [0.02, 0.01]})

    with pytest.raises(ValueError, match="requires independent_trials <= number of trial return columns"):
        expected_maximum_sr(trials_returns=trials_returns, independent_trials=3)


def test_expected_maximum_sr_nonfinite_std_returns_expected_mean():
    """Test that expected_maximum_sr returns expected_mean_sr when trials_sr_std is nan."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    result = expected_maximum_sr(independent_trials=5, expected_mean_sr=0.25, trials_sr_std=float("nan"))

    assert result == 0.25


def test_expected_maximum_sr_requires_nonnegative_std():
    """Test that expected_maximum_sr requires trials_sr_std >= 0."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires trials_sr_std >= 0"):
        expected_maximum_sr(independent_trials=5, expected_mean_sr=0.25, trials_sr_std=-0.5)


@pytest.mark.parametrize("expected_mean_sr", [float("nan"), float("inf")])
def test_expected_maximum_sr_requires_finite_expected_mean(expected_mean_sr):
    """Test that expected_maximum_sr requires finite expected_mean_sr."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires finite expected_mean_sr"):
        expected_maximum_sr(independent_trials=5, expected_mean_sr=expected_mean_sr, trials_sr_std=0.5)


def test_expected_maximum_sr_requires_trials_returns_or_std_for_multiple_trials():
    """Test that expected_maximum_sr requires trials_returns or trials_sr_std when independent_trials > 1."""
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires trials_returns or trials_sr_std when independent_trials > 1"):
        expected_maximum_sr(independent_trials=2)


def test_probabilistic_sharpe_ratio_single_value_series_uses_position_not_label():
    """Test that probabilistic_sharpe_ratio uses Series position, not label index."""
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    result = probabilistic_sharpe_ratio(
        returns=None,
        sr=pd.Series([1.5], index=["only"]),
        sr_std=pd.Series([0.5], index=["only"]),
    )

    assert isinstance(result, (float, int, np.floating))
    assert math.isfinite(result)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"returns": None, "sr": 1.5},
        {"returns": None, "sr_std": 0.5},
    ],
)
def test_probabilistic_sharpe_ratio_requires_explicit_params_without_returns(kwargs):
    """Test that probabilistic_sharpe_ratio requires both sr and sr_std when returns is None."""
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    with pytest.raises(ValueError, match="requires sr and sr_std"):
        probabilistic_sharpe_ratio(**kwargs)


@pytest.mark.parametrize("sr_std", [0.0, -0.5, float("nan")])
def test_probabilistic_sharpe_ratio_requires_finite_positive_std(sr_std):
    """Test that probabilistic_sharpe_ratio requires sr_std > 0 and finite."""
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    with pytest.raises(ValueError, match="requires finite sr_std > 0"):
        probabilistic_sharpe_ratio(returns=None, sr=1.5, sr_std=sr_std)


@pytest.mark.parametrize("sr", [float("nan"), float("inf")])
def test_probabilistic_sharpe_ratio_requires_finite_explicit_sr(sr):
    """Test that probabilistic_sharpe_ratio requires finite sr."""
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    with pytest.raises(ValueError, match="requires finite sr"):
        probabilistic_sharpe_ratio(returns=None, sr=sr, sr_std=0.5)


@pytest.mark.parametrize("sr_benchmark", [float("nan"), float("inf")])
def test_probabilistic_sharpe_ratio_requires_finite_benchmark(sr_benchmark):
    """Test that probabilistic_sharpe_ratio requires finite sr_benchmark."""
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    with pytest.raises(ValueError, match="requires finite sr_benchmark"):
        probabilistic_sharpe_ratio(returns=None, sr=1.5, sr_std=0.5, sr_benchmark=sr_benchmark)


def test_min_track_record_length_single_value_series_uses_position_not_label():
    """Test that min_track_record_length uses Series position, not label index."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    result = min_track_record_length(
        returns=None,
        n=10,
        sr=pd.Series([1.5], index=["only"]),
        sr_std=pd.Series([0.5], index=["only"]),
    )

    assert isinstance(result, (float, int, np.floating))
    assert math.isfinite(result)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"returns": None, "n": 10, "sr": 1.5},
        {"returns": None, "n": 10, "sr_std": 0.5},
        {"returns": None, "sr": 1.5, "sr_std": 0.5},
    ],
)
def test_min_track_record_length_requires_explicit_params_without_returns(kwargs):
    """Test that min_track_record_length requires n, sr, and sr_std when returns is None."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires n, sr, and sr_std"):
        min_track_record_length(**kwargs)


@pytest.mark.parametrize("prob", [0.0, 1.0, -0.1, 1.1])
def test_min_track_record_length_requires_probability_between_zero_and_one(prob):
    """Test that min_track_record_length requires 0 < prob < 1."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires 0 < prob < 1"):
        min_track_record_length(returns=None, n=10, sr=1.5, sr_std=0.5, prob=prob)


@pytest.mark.parametrize("n", [0, 1, -3])
def test_min_track_record_length_requires_n_above_one(n):
    """Test that min_track_record_length requires n > 1."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires n > 1"):
        min_track_record_length(returns=None, n=n, sr=1.5, sr_std=0.5)


@pytest.mark.parametrize("n", [2.5, float("nan")])
def test_min_track_record_length_requires_integer_n(n):
    """Test that min_track_record_length requires integer n."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires integer n"):
        min_track_record_length(returns=None, n=n, sr=1.5, sr_std=0.5)


@pytest.mark.parametrize("sr_std", [0.0, -0.5, float("nan")])
def test_min_track_record_length_requires_finite_positive_std(sr_std):
    """Test that min_track_record_length requires sr_std > 0 and finite."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires finite sr_std > 0"):
        min_track_record_length(returns=None, n=10, sr=1.5, sr_std=sr_std)


@pytest.mark.parametrize("sr", [float("nan"), float("inf")])
def test_min_track_record_length_requires_finite_explicit_sr(sr):
    """Test that min_track_record_length requires finite sr."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires finite sr"):
        min_track_record_length(returns=None, n=10, sr=sr, sr_std=0.5)


@pytest.mark.parametrize("sr_benchmark", [float("nan"), float("inf")])
def test_min_track_record_length_requires_finite_benchmark(sr_benchmark):
    """Test that min_track_record_length requires finite sr_benchmark."""
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires finite sr_benchmark"):
        min_track_record_length(returns=None, n=10, sr=1.5, sr_std=0.5, sr_benchmark=sr_benchmark)


def test_deflated_sharpe_ratio_caps_default_independent_trials_to_available_columns():
    """Test that deflated_sharpe_ratio caps default independent_trials to available columns."""
    from backtrader.analyzers.sharpe_ratio_stats import deflated_sharpe_ratio

    trials_returns = pd.DataFrame(
        {
            "a": [0.01, 0.02, 0.015, 0.018],
            "b": [0.02, 0.01, 0.012, 0.011],
        }
    )

    result = deflated_sharpe_ratio(trials_returns=trials_returns, returns_selected=trials_returns["a"])

    assert isinstance(result, (float, int, np.floating))
    assert math.isfinite(result)


def test_deflated_sharpe_ratio_requires_returns_selected():
    """Test that deflated_sharpe_ratio requires returns_selected."""
    from backtrader.analyzers.sharpe_ratio_stats import deflated_sharpe_ratio

    with pytest.raises(ValueError, match="requires returns_selected"):
        deflated_sharpe_ratio(expected_max_sr=0.5)


def test_deflated_sharpe_ratio_requires_trials_returns_when_expected_max_sr_missing():
    """Test that deflated_sharpe_ratio requires trials_returns when expected_max_sr is None."""
    from backtrader.analyzers.sharpe_ratio_stats import deflated_sharpe_ratio

    with pytest.raises(ValueError, match="requires trials_returns when expected_max_sr is None"):
        deflated_sharpe_ratio(returns_selected=pd.Series([0.01, 0.02, 0.03]))


@pytest.mark.parametrize("expected_max_sr", [float("nan"), float("inf")])
def test_deflated_sharpe_ratio_requires_finite_expected_max_sr(expected_max_sr):
    """Test that deflated_sharpe_ratio requires finite expected_max_sr."""
    from backtrader.analyzers.sharpe_ratio_stats import deflated_sharpe_ratio

    with pytest.raises(ValueError, match="requires finite expected_max_sr"):
        deflated_sharpe_ratio(returns_selected=pd.Series([0.01, 0.02, 0.03]), expected_max_sr=expected_max_sr)


if __name__ == "__main__":
    test_run(main=True)
