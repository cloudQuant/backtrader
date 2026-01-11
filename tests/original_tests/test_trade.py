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

"""Test module for backtrader Trade class functionality.

This module contains unit tests for the Trade class, which tracks the lifecycle
of trades in the backtrader framework. The tests verify trade state management,
including position updates, price calculations, commission tracking, and trade
closure conditions.

The tests use mock objects (FakeCommInfo, FakeData) to isolate the Trade class
behavior from the full backtrader framework.
"""

import backtrader as bt


class FakeCommInfo:
    """Mock commission info object for testing.

    This class provides a minimal implementation of the commission info interface
    required by the Trade class during testing. All methods return zero to isolate
    the Trade class behavior from commission calculations.
    """

    def getvaluesize(self, size, price):
        """Calculate the value size for a given position.

        Args:
            size: Position size (number of units/contracts).
            price: Price per unit.

        Returns:
            float: Always returns 0 for testing purposes.
        """
        return 0

    def profitandloss(self, size, price, newprice):
        """Calculate profit and loss for a position.

        Args:
            size: Position size (number of units/contracts).
            price: Original entry price.
            newprice: Current or exit price.

        Returns:
            float: Always returns 0 for testing purposes.
        """
        return 0


class FakeData:
    """Mock data feed object for testing.

    This class provides a minimal implementation of the data feed interface
    required by the Trade class during testing. It prevents errors when the Trade
    class attempts to access information from the data feed.

    Attributes:
        datetime: Mock datetime property returning a default value.
        close: Mock close price property returning a default value.
    """

    def __len__(self):
        """Return the length of the data feed.

        Returns:
            int: Always returns 0 for testing purposes.
        """
        return 0

    @property
    def datetime(self):
        """Get the datetime values for the data feed.

        Returns:
            list: A list containing a single default datetime value (0.0).
        """
        return [0.0]

    @property
    def close(self):
        """Get the close price values for the data feed.

        Returns:
            list: A list containing a single default close price (0.0).
        """
        return [0.0]


def test_run(main=False):
    """Test the Trade class lifecycle and state management.

    This test verifies the behavior of the Trade class through a complete
    trade lifecycle, including:
    1. Initial position opening
    2. Position reduction (partial close)
    3. Position increase (adding to existing position)
    4. Complete position closure

    The test validates:
    - Trade size tracking and updates
    - Average price calculation (weighted average for increases)
    - Commission accumulation
    - Trade closure detection
    - Price behavior during position changes (should not change when reducing)

    Args:
        main (bool, optional): If True, indicates the test is being run as
            the main module. Defaults to False.

    Raises:
        AssertionError: If any of the trade state assertions fail.
    """
    tr = bt.Trade(data=FakeData())

    order = bt.BuyOrder(
        data=FakeData(), size=0, price=1.0, exectype=bt.Order.Market, simulated=True
    )

    commrate = 0.025
    size = 10
    price = 10.0
    value = size * price
    commission = value * commrate

    tr.update(
        order=order,
        size=size,
        price=price,
        value=value,
        commission=commission,
        pnl=0.0,
        comminfo=FakeCommInfo(),
    )

    assert not tr.isclosed
    assert tr.size == size
    assert tr.price == price
    # assert tr.value == value
    assert tr.commission == commission
    assert not tr.pnl
    assert tr.pnlcomm == tr.pnl - tr.commission

    upsize = -5
    upprice = 12.5
    upvalue = upsize * upprice
    upcomm = abs(value) * commrate

    tr.update(
        order=order,
        size=upsize,
        price=upprice,
        value=upvalue,
        commission=upcomm,
        pnl=0.0,
        comminfo=FakeCommInfo(),
    )

    assert not tr.isclosed
    assert tr.size == size + upsize
    assert tr.price == price  # size is being reduced, price must not change
    # assert tr.value == upvalue
    assert tr.commission == commission + upcomm

    size = tr.size
    price = tr.price
    commission = tr.commission

    upsize = 7
    upprice = 14.5
    upvalue = upsize * upprice
    upcomm = abs(value) * commrate

    tr.update(
        order=order,
        size=upsize,
        price=upprice,
        value=upvalue,
        commission=upcomm,
        pnl=0.0,
        comminfo=FakeCommInfo(),
    )

    assert not tr.isclosed
    assert tr.size == size + upsize
    assert tr.price == ((size * price) + (upsize * upprice)) / (size + upsize)
    # assert tr.value == upvalue
    assert tr.commission == commission + upcomm

    size = tr.size
    price = tr.price
    commission = tr.commission

    upsize = -size
    upprice = 12.5
    upvalue = upsize * upprice
    upcomm = abs(value) * commrate

    tr.update(
        order=order,
        size=upsize,
        price=upprice,
        value=upvalue,
        commission=upcomm,
        pnl=0.0,
        comminfo=FakeCommInfo(),
    )

    assert tr.isclosed
    assert tr.size == size + upsize
    assert tr.price == price  # no change ... we simple closed the operation
    # assert tr.value == upvalue
    assert tr.commission == commission + upcomm


if __name__ == "__main__":
    test_run(main=True)
