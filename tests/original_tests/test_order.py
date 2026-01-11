#!/usr/bin/env python
###############################################################################
#
# Copyright (C) 2015-2023 Daniel Rodriguez
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

"""Test suite for order execution and pending order tracking.

This module contains tests to verify that order execution properly maintains
the correct iterpending sequence. When orders are partially executed and
cloned for each notification, the pending bits should be reported relative
to the previous notification (clone).

The test verifies that:
1. Partial order execution creates pending execution records
2. Cloned orders maintain the correct pending sequence
3. Multiple partial executions are tracked correctly
4. The pending records always reflect the most recent notifications
"""

import backtrader as bt


class FakeCommInfo:
    """Fake commission info object for testing purposes.

    This class provides a minimal implementation of the commission info
    interface used by backtrader, returning zero values for all calculations.
    It allows tests to run without requiring a full commission info setup.
    """

    def getvaluesize(self, size, price):
        """Calculate the value size for a given position size and price.

        Args:
            size (float): The position size.
            price (float): The price per unit.

        Returns:
            float: Always returns 0 for testing purposes.
        """
        return 0

    def profitandloss(self, size, price, newprice):
        """Calculate the profit and loss for a position.

        Args:
            size (float): The position size.
            price (float): The original price.
            newprice (float): The current price.

        Returns:
            float: Always returns 0 for testing purposes.
        """
        return 0

    def getoperationcost(self, size, price):
        """Calculate the operation cost for a trade.

        Args:
            size (float): The position size.
            price (float): The price per unit.

        Returns:
            float: Always returns 0.0 for testing purposes.
        """
        return 0.0

    def getcommission(self, size, price):
        """Calculate the commission for a trade.

        Args:
            size (float): The position size.
            price (float): The price per unit.

        Returns:
            float: Always returns 0.0 for testing purposes.
        """
        return 0.0


class FakeData:
    """Fake data feed object for testing purposes.

    This class provides a minimal interface to avoid errors when a trade
    tries to get information from the data feed during testing. It returns
    default zero values for all properties.
    """

    def __len__(self):
        """Return the length of the data feed.

        Returns:
            int: Always returns 0 for testing purposes.
        """
        return 0

    @property
    def datetime(self):
        """Get the datetime values of the data feed.

        Returns:
            list: Always returns [0.0] for testing purposes.
        """
        return [0.0]

    @property
    def close(self):
        """Get the close prices of the data feed.

        Returns:
            list: Always returns [0.0] for testing purposes.
        """
        return [0.0]


def _execute(position, order, size, price, partial):
    """Execute a trade order and update the position and order status.

    This helper function performs a real order execution, updating the position
    and recording all relevant trade information including commissions, profit
    and loss, and margin requirements.

    Args:
        position (bt.Position): The position object to update.
        order (bt.Order): The order being executed.
        size (float): The size of the execution.
        price (float): The price of the execution.
        partial (bool): Whether this is a partial execution (True) or complete
            execution (False).

    The function calculates:
    - Position updates (size, price, opened, closed amounts)
    - Closed value and commission
    - Opened value and commission
    - Profit and loss
    - Margin requirements
    """
    # Find position and do a real update - accounting happens here
    pprice_orig = position.price
    psize, pprice, opened, closed = position.update(size, price)

    comminfo = order.comminfo
    closedvalue = comminfo.getoperationcost(closed, pprice_orig)
    closedcomm = comminfo.getcommission(closed, price)

    openedvalue = comminfo.getoperationcost(opened, price)
    openedcomm = comminfo.getcommission(opened, price)

    pnl = comminfo.profitandloss(-closed, pprice_orig, price)
    margin = comminfo.getvaluesize(size, price)

    order.execute(
        order.data.datetime[0],
        size,
        price,
        closed,
        closedvalue,
        closedcomm,
        opened,
        openedvalue,
        openedcomm,
        margin,
        pnl,
        psize,
        pprice,
    )  # pnl

    if partial:
        order.partial()
    else:
        order.completed()


def test_run(main=False):
    """Test that partially updating order maintains correct iterpending sequence.

    This test verifies that when orders are cloned for each notification,
    the pending bits are correctly reported relative to the previous
    notification (clone).

    The test performs two rounds of partial executions:
    1. First round: Execute 10 and 20 units, verify 2 pending records
    2. Second round: Execute 30 and 40 units, verify 2 pending records

    Each round validates that the cloned order's pending records match
    the most recent executions.

    Args:
        main (bool): Whether this is being run as the main script.
            Defaults to False.

    Raises:
        AssertionError: If any of the pending record assertions fail.
    """
    position = bt.Position()
    comminfo = FakeCommInfo()
    order = bt.BuyOrder(
        data=FakeData(), size=100, price=1.0, exectype=bt.Order.Market, simulated=True
    )
    order.addcomminfo(comminfo)

    ### Test that partially updating order will maintain correct iterpending sequence
    ### (Orders are cloned for each notification. The pending bits should be reported
    ###  related to the previous notification (clone))

    # Add two bits and validate we have two pending bits
    _execute(position, order, 10, 1.0, True)
    _execute(position, order, 20, 1.1, True)

    clone = order.clone()
    pending = clone.executed.getpending()
    assert len(pending) == 2
    assert pending[0].size == 10
    assert pending[0].price == 1.0
    assert pending[1].size == 20
    assert pending[1].price == 1.1

    # Add additional two bits and validate we still have two pending bits after clone
    _execute(position, order, 30, 1.2, True)
    _execute(position, order, 40, 1.3, False)

    clone = order.clone()
    pending = clone.executed.getpending()
    assert len(pending) == 2
    assert pending[0].size == 30
    assert pending[0].price == 1.2
    assert pending[1].size == 40
    assert pending[1].price == 1.3


if __name__ == "__main__":
    test_run(main=True)
