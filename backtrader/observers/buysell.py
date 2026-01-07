#!/usr/bin/env python
"""BuySell Observer Module - Buy/sell signal visualization.

This module provides the BuySell observer for visualizing buy and sell
orders on the chart.

Classes:
    BuySell: Observer that plots buy/sell markers on the chart.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.BuySell)
"""

import math

from ..observer import Observer


# Buy and sell point markers
class BuySell(Observer):
    """
    This observer keeps track of the individual buy/sell orders (individual
    executions) and will plot them on the chart along the data around the
    execution price level

    Params:
      - ``barplot`` (default: ``False``) Plot buy signals below the minimum and
        sell signals above the maximum.

        If `False`, it will plot on the average price of executions during a
        bar

      - ``bardist`` (default: ``0.015`` 1.5%) Distance to max/min when
        ``barplot`` is ``True``
    """

    lines = (
        "buy",
        "sell",
    )

    plotinfo = dict(plot=True, subplot=False, plotlinelabels=True)
    plotlines = dict(
        buy=dict(marker="^", markersize=8.0, color="lime", fillstyle="full", ls=""),
        sell=dict(marker="v", markersize=8.0, color="red", fillstyle="full", ls=""),
    )

    params = (
        ("barplot", False),  # plot above/below max/min for clarity in bar plot
        ("bardist", 0.015),  # distance to max/min in absolute perc
    )

    def __init__(self):
        """Initialize the BuySell observer.

        Sets up tracking for buy/sell order lengths.
        """
        self.curbuylen = None

    def next(self):
        """Update buy/sell markers based on executed orders.

        Calculates average prices for buy and sell orders during the bar.
        """
        buy = list()
        sell = list()
        # If there are pending orders
        for order in self._owner._orderspending:
            # If no data or size is 0, skip
            if order.data is not self.data or not order.executed.size:
                continue
            # If it's a buy order, add price to buy, if it's a sell order, add price to sell
            if order.isbuy():
                buy.append(order.executed.price)
            else:
                sell.append(order.executed.price)

        # Take into account replay ... something could already be in there
        # Write down the average buy/sell price

        # BUY
        # Get buy price
        curbuy = self.lines.buy[0]
        # If NaN, curbuy equals 0, curbuylen=0, otherwise, curbuylen = self.curbuylen
        if curbuy != curbuy:  # NaN
            curbuy = 0.0
            self.curbuylen = curbuylen = 0
        else:
            curbuylen = self.curbuylen
        # Current total price
        buyops = curbuy + math.fsum(buy)
        # Current total order count
        buylen = curbuylen + len(buy)
        # Calculate average price
        value = buyops / float(buylen or "NaN")
        # If not plotting, get average price, if plotting, get a percentage of lowest price for better display
        if not self.p.barplot:
            self.lines.buy[0] = value
        elif value == value:  # Not NaN
            pbuy = self.data.low[0] * (1 - self.p.bardist)
            self.lines.buy[0] = pbuy

        # Update buylen values
        curbuy = buyops
        self.curbuylen = buylen

        # For sell orders, similar logic
        # SELL
        cursell = self.lines.sell[0]
        if cursell != cursell:  # NaN
            cursell = 0.0
            self.curselllen = curselllen = 0
        else:
            curselllen = self.curselllen

        sellops = cursell + math.fsum(sell)
        selllen = curselllen + len(sell)

        value = sellops / float(selllen or "NaN")
        if not self.p.barplot:
            self.lines.sell[0] = value
        elif value == value:  # Not NaN
            psell = self.data.high[0] * (1 + self.p.bardist)
            self.lines.sell[0] = psell

        # Update selllen values
        cursell = sellops
        self.curselllen = selllen
