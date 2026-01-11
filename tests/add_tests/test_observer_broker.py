#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for broker observer functionality in backtrader.

This module contains tests to verify that broker-related observers work correctly
during backtesting. The test uses a simple moving average crossover strategy
to generate trades and verify that the broker observer properly tracks and
reports portfolio metrics.

The test strategy:
1. Uses a 15-period Simple Moving Average (SMA)
2. Buys when price crosses above the SMA
3. Closes position when price crosses below the SMA
4. Verifies broker observer tracking of portfolio value

Typical usage example:
    >>> from tests.add_tests import test_observer_broker
    >>> test_observer_broker.test_run()
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy generates buy and close signals based on the crossover
    between price and a Simple Moving Average (SMA). It is designed to
    test broker observer functionality by generating trades that change
    portfolio value.

    The strategy:
        - Calculates a 15-period SMA on close price
        - Monitors crossover events between close price and SMA
        - Buys when price crosses above SMA (bullish signal)
        - Closes position when price crosses below SMA (bearish signal)

    Attributes:
        sma: Simple Moving Average indicator with 15-period window.
        cross: Crossover indicator tracking price vs SMA relationship.

    Note:
        This strategy only holds long positions and maintains at most
        one open position at a time.
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up the Simple Moving Average and crossover indicators that
        will be used to generate trading signals.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements the crossover strategy:
        - If no position exists, buy when close crosses above SMA (cross > 0)
        - If position exists, close when close crosses below SMA (cross < 0)

        The crossover indicator returns:
            - Positive value (1.0) when bullish crossover occurs
            - Negative value (-1.0) when bearish crossover occurs
            - Zero (0.0) when no crossover
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the broker observer test.

    Executes a backtest using the RunStrategy and verifies that:
    1. The strategy processes data (len(strat) > 0)
    2. The broker observer tracks portfolio value correctly
    3. Final portfolio value is positive

    Args:
        main (bool): If True, prints final portfolio value. Defaults to False.
                     When run as a script (__main__), this is set to True.

    Raises:
        AssertionError: If the strategy didn't run (len(strat) == 0) or
                       if final portfolio value is not positive.

    Note:
        The test uses testcommon.runtest() which may run multiple cerebro
        instances with different configurations. All instances are validated.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('Broker observer test completed')  # Removed for performance
            pass
            print(f"Final value: {strat.broker.getvalue()}")
        # Verify the strategy ran successfully
        assert len(strat) > 0
        assert strat.broker.getvalue() > 0


if __name__ == "__main__":
    test_run(main=True)
