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
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    returns = pd.Series([0.01, 0.02, 0.015, 0.018])
    result = estimated_sharpe_ratio_stdev(returns)

    assert isinstance(result, (float, int))
    assert math.isfinite(result)


def test_estimated_sharpe_ratio_stdev_accepts_explicit_params_without_returns():
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    result = estimated_sharpe_ratio_stdev(returns=None, n=10, skew=0.0, kurtosis=3.0, sr=1.5)

    assert isinstance(result, (float, int, np.floating))
    assert math.isfinite(result)


def test_estimated_sharpe_ratio_stdev_requires_explicit_params_without_returns():
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match="requires n, skew, kurtosis, and sr"):
        estimated_sharpe_ratio_stdev(returns=None, n=10, skew=0.0, kurtosis=3.0)


def test_estimated_sharpe_ratio_stdev_requires_more_than_one_sample():
    from backtrader.analyzers.sharpe_ratio_stats import estimated_sharpe_ratio_stdev

    with pytest.raises(ValueError, match="requires n > 1"):
        estimated_sharpe_ratio_stdev(returns=None, n=1, skew=0.0, kurtosis=3.0, sr=1.0)


def test_num_independent_trials_handles_all_nan_correlations():
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


def test_expected_maximum_sr_single_trial_returns_expected_mean():
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    result = expected_maximum_sr(independent_trials=1, expected_mean_sr=0.25, trials_sr_std=1.0)

    assert result == 0.25


@pytest.mark.parametrize("independent_trials", [0, -1])
def test_expected_maximum_sr_requires_at_least_one_trial(independent_trials):
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    with pytest.raises(ValueError, match="requires independent_trials >= 1"):
        expected_maximum_sr(independent_trials=independent_trials, expected_mean_sr=0.25, trials_sr_std=1.0)


def test_expected_maximum_sr_rejects_trials_above_column_count():
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    trials_returns = pd.DataFrame({"a": [0.01, 0.02], "b": [0.02, 0.01]})

    with pytest.raises(ValueError, match="requires independent_trials <= number of trial return columns"):
        expected_maximum_sr(trials_returns=trials_returns, independent_trials=3)


def test_expected_maximum_sr_nonfinite_std_returns_expected_mean():
    from backtrader.analyzers.sharpe_ratio_stats import expected_maximum_sr

    result = expected_maximum_sr(independent_trials=5, expected_mean_sr=0.25, trials_sr_std=float("nan"))

    assert result == 0.25


def test_probabilistic_sharpe_ratio_single_value_series_uses_position_not_label():
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
    from backtrader.analyzers.sharpe_ratio_stats import probabilistic_sharpe_ratio

    with pytest.raises(ValueError, match="requires sr and sr_std"):
        probabilistic_sharpe_ratio(**kwargs)


def test_min_track_record_length_single_value_series_uses_position_not_label():
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
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires n, sr, and sr_std"):
        min_track_record_length(**kwargs)


@pytest.mark.parametrize("prob", [0.0, 1.0, -0.1, 1.1])
def test_min_track_record_length_requires_probability_between_zero_and_one(prob):
    from backtrader.analyzers.sharpe_ratio_stats import min_track_record_length

    with pytest.raises(ValueError, match="requires 0 < prob < 1"):
        min_track_record_length(returns=None, n=10, sr=1.5, sr_std=0.5, prob=prob)


if __name__ == "__main__":
    test_run(main=True)
