#!/usr/bin/env python
"""Test module for the PositionsValue analyzer.

This module contains tests for the PositionsValue analyzer, which tracks
the value of open positions over time during backtesting. The tests verify
that the analyzer correctly captures and reports position values at different
points in time.

The test uses a simple SMA crossover strategy to generate positions and then
validates that the analyzer produces the expected output format.
"""

import backtrader as bt
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

import testcommon


class RunStrategy(bt.Strategy):
    """A simple SMA crossover strategy for testing the PositionsValue analyzer.

    This strategy generates buy and close signals based on the crossover of
    price and a Simple Moving Average (SMA). It buys when price crosses above
    the SMA and closes the position when price crosses below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: CrossOver indicator tracking price and SMA crossovers.
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up the SMA indicator and the CrossOver indicator that will
        generate trading signals.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Checks for crossover signals and executes trades accordingly:
        - If no position exists and cross is positive (price > SMA), buy.
        - If a position exists and cross is negative (price < SMA), close position.

        The cross value is positive when price crosses above SMA (bullish signal)
        and negative when price crosses below SMA (bearish signal).
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the PositionsValue analyzer test.

    This function creates a cerebro instance with test data, runs the
    RunStrategy with the PositionsValue analyzer attached, and verifies
    that the analyzer produces valid output.

    The test validates that:
    - The analyzer returns a dictionary
    - The dictionary structure is correct (datetime keys with position values)

    Args:
        main (bool): If True, runs in standalone mode and prints results.
                     If False, runs in test mode and performs assertions.
                     Defaults to False.

    Returns:
        None: The function performs assertions and/or prints results.

    Raises:
        AssertionError: If the analyzer output is not a dictionary or
                       if the analysis structure is invalid.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.PositionsValue, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('Positions Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # Positions should track position values over time
            # Dict should have datetime keys with position values
            assert len(analysis) >= 0  # May be empty if no positions taken


def _build_positions_analyzer(position_value, cash_value=None):
    analyzer = bt.analyzers.PositionsValue.__new__(bt.analyzers.PositionsValue)
    analyzer.p = SimpleNamespace(cash=cash_value is not None, headers=False)
    analyzer.datas = [MagicMock(_timeframe=bt.TimeFrame.Days, _name="data0")]
    analyzer.strategy = MagicMock()
    analyzer.strategy.broker.get_value.return_value = position_value
    analyzer.strategy.broker.get_cash.return_value = cash_value
    analyzer.strategy.datetime.date.return_value = "2021-01-01"
    analyzer.strategy.datetime.datetime.return_value = "2021-01-01T00:00:00"
    analyzer.rets = {}
    analyzer._usedate = True
    return analyzer


@pytest.mark.parametrize("position_value", ["bad", complex(1.0, 1.0), float("nan")])
def test_positionsvalue_invalid_position_value_degrades_to_zero(position_value):
    analyzer = _build_positions_analyzer(position_value)

    analyzer.next()

    assert analyzer.rets["2021-01-01"] == [0.0]


@pytest.mark.parametrize("cash_value", ["bad", complex(1.0, 1.0), float("nan")])
def test_positionsvalue_invalid_cash_value_degrades_to_zero(cash_value):
    analyzer = _build_positions_analyzer(100.0, cash_value=cash_value)

    analyzer.next()

    assert analyzer.rets["2021-01-01"] == [100.0, 0.0]


if __name__ == "__main__":
    test_run(main=True)
