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

"""Test module for the Position class in backtrader.

This module tests the functionality of the bt.Position class, which manages
position state including size and price. The tests verify:

1. Initial position creation with size and price
2. Position updates when opening new positions (increasing size)
3. Position updates when closing positions (decreasing size)
4. Position updates when flipping positions (closing and opening in opposite direction)
5. Correct calculation of average price during position updates
6. Proper tracking of opened and closed amounts

The test covers various scenarios including:
- Opening long positions
- Partially closing positions
- Fully closing positions
- Flipping from long to short positions
"""

import backtrader as bt


def test_run(main=False):
    """Test Position class functionality including creation and updates.

    This test function verifies the behavior of the bt.Position class through
    three main scenarios:

    1. **Opening a position**: Tests that adding to a position correctly
       calculates the new average price and tracks the opened amount.

    2. **Partial close**: Tests that partially closing a position maintains
       the original average price and correctly tracks the closed amount.

    3. **Position flip**: Tests that closing more than the current position
       (flipping to the opposite direction) correctly sets the new price
       and tracks both closed and opened amounts.

    Args:
        main (bool, optional): If True, prints intermediate results for
            manual verification. Defaults to False.

    Returns:
        None: This function performs assertions and returns nothing.

    Raises:
        AssertionError: If any of the position calculations are incorrect,
            including size, price, opened amount, or closed amount.
    """
    size = 10
    price = 10.0

    pos = bt.Position(size=size, price=price)
    assert pos.size == size
    assert pos.price == price

    upsize = 5
    upprice = 12.5
    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print("nsize, nprice, opened, closed", nsize, nprice, opened, closed)

    assert pos.size == size + upsize
    assert pos.size == nsize
    assert pos.price == ((size * price) + (upsize * upprice)) / pos.size
    assert pos.price == nprice
    assert opened == upsize
    assert not closed

    size = pos.size
    price = pos.price
    upsize = -7
    upprice = 14.5

    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print("nsize, nprice, opened, closed", nsize, nprice, opened, closed)

    assert pos.size == size + upsize

    assert pos.size == nsize
    assert pos.price == price
    assert pos.price == nprice
    assert not opened
    assert closed == upsize  # the closed must have the sign of "update" size

    size = pos.size
    price = pos.price
    upsize = -15
    upprice = 17.5

    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print("nsize, nprice, opened, closed", nsize, nprice, opened, closed)

    assert pos.size == size + upsize
    assert pos.size == nsize
    assert pos.price == upprice
    assert pos.price == nprice
    assert opened == size + upsize
    assert closed == -size


if __name__ == "__main__":
    test_run(main=True)
