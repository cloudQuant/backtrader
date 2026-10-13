#!/usr/bin/env python
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
"""Simple Moving Average (SMA) Crossover Strategy Example.

This module demonstrates a basic long-only trading strategy based on moving
average crossovers using the backtrader framework. The strategy generates buy
signals when the fast moving average crosses above the slow moving average,
and sell signals when the fast moving average crosses below the slow moving
average.

Example:
    To run this strategy with default parameters::

        import backtrader as bt

        cerebro = bt.Cerebro()
        cerebro.addstrategy(MA_CrossOver, fast=10, slow=30)
        cerebro.run()

    The strategy can also be accessed via its alias::

        cerebro.addstrategy(SMA_CrossOver, fast=10, slow=30)
"""
import backtrader as bt
import backtrader.indicators as btind


class MA_CrossOver(bt.Strategy):
    """A long-only moving average crossover trading strategy.

    This strategy generates buy and sell signals based on the crossover of
    two moving averages with different periods. It only takes long positions
    and uses market orders for execution.

    Buy Logic:
        - No position is currently open on the data
        - The fast moving average crosses over the slow moving average to
          the upside (bullish crossover)

    Sell Logic:
        - A position exists on the data
        - The fast moving average crosses over the slow moving average to
          the downside (bearish crossover)

    Order Execution Type:
        - Market orders are used for both buy and sell signals

    Attributes:
        buysig (bt.indicators.CrossOver): Crossover indicator that generates
            signals. Positive values indicate bullish crossover (buy signal),
            negative values indicate bearish crossover (sell signal).
        position (backtrader.position.Position): Current position object
            providing access to position size and status.

    Note:
        This strategy is long-only, meaning it only enters long positions and
        closes existing positions. It never short sells.
    """

    alias = ("SMA_CrossOver",)

    params = (
        # period for the fast Moving Average
        ("fast", 10),
        # period for the slow moving average
        ("slow", 30),
        # moving average to use
        ("_movav", btind.MovAv.SMA),
    )

    def __init__(self):
        """Initialize the MA_CrossOver strategy.

        Sets up the moving average indicators and the crossover signal
        indicator that will be used to generate buy and sell signals.

        The method creates:
        1. A fast moving average with the period specified by params.fast
        2. A slow moving average with the period specified by params.slow
        3. A crossover indicator that monitors the relationship between
           the two moving averages
        """
        sma_fast = self.p._movav(period=self.p.fast)
        sma_slow = self.p._movav(period=self.p.slow)

        self.buysig = btind.CrossOver(sma_fast, sma_slow)

    def next(self):
        """Execute trading logic for the current bar.

        This method is called for each bar of data after the minimum period
        has been reached. It implements the core trading logic:

        1. If a position exists and the crossover signal is negative (bearish),
           close the position by selling.
        2. If no position exists and the crossover signal is positive (bullish),
           open a long position by buying.

        The strategy ensures only one position is open at a time and uses
        market orders for immediate execution.
        """
        if self.position.size:
            if self.buysig < 0:
                self.sell()

        elif self.buysig > 0:
            self.buy()
