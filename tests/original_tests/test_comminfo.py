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

"""Test module for CommissionInfo functionality.

This module contains tests to verify the correct behavior of the CommissionInfo
class for different asset types, including stocks and futures. It tests various
commission-related calculations such as operation costs, position values,
commission costs, profit and loss, and cash adjustments.

The tests ensure that commission calculations are accurate for both stock
trading (where commission is a percentage of the trade value) and futures
trading (where commission involves margin and multiplier considerations).
"""

import backtrader as bt

from backtrader import Position


def check_stocks():
    """Test commission calculations for stock trading.

    This function verifies that CommissionInfo correctly calculates various
    values for stock positions where commission is a percentage of the trade
    value. It tests:

    1. Operation cost equals size * price (full trade value)
    2. Position value equals size * price
    3. Commission cost equals size * price * commission rate
    4. Profit and loss equals size * (new_price - original_price)
    5. No cash adjustment is needed for stocks

    Raises:
        AssertionError: If any of the commission calculations are incorrect.
    """
    commission = 0.5
    comm = bt.CommissionInfo(commission=commission)

    price = 10.0
    cash = 10000.0
    size = 100.0

    opcost = comm.getoperationcost(size=size, price=price)
    assert opcost == size * price

    pos = bt.Position(size=size, price=price)
    value = comm.getvalue(pos, price)
    assert value == size * price

    commcost = comm.getcommission(size, price)
    assert commcost == size * price * commission

    newprice = 5.0
    pnl = comm.profitandloss(pos.size, pos.price, newprice)
    assert pnl == pos.size * (newprice - price)

    ca = comm.cashadjust(size, price, newprice)
    assert not ca


def check_futures():
    """Test commission calculations for futures trading.

    This function verifies that CommissionInfo correctly calculates various
    values for futures positions where commission involves margin and multiplier
    considerations. It tests:

    1. Operation cost equals size * margin (not the full contract value)
    2. Position value equals size * margin
    3. Commission cost equals size * commission (per contract)
    4. Profit and loss equals size * (new_price - original_price) * multiplier
    5. Cash adjustment equals size * (new_price - original_price) * multiplier

    The multiplier ensures that price changes are properly scaled according
    to the futures contract specifications.

    Raises:
        AssertionError: If any of the commission calculations are incorrect.
    """
    commission = 0.5
    margin = 10.0
    mult = 10.0
    comm = bt.CommissionInfo(commission=commission, mult=mult, margin=margin)

    price = 10.0
    cash = 10000.0
    size = 100.0

    opcost = comm.getoperationcost(size=size, price=price)
    assert opcost == size * margin

    pos = bt.Position(size=size, price=price)
    value = comm.getvalue(pos, price)
    assert value == size * margin

    commcost = comm.getcommission(size, price)
    assert commcost == size * commission

    newprice = 5.0
    pnl = comm.profitandloss(pos.size, pos.price, newprice)
    assert pnl == pos.size * (newprice - price) * mult

    ca = comm.cashadjust(size, price, newprice)
    assert ca == size * (newprice - price) * mult


def test_run(main=False):
    """Run all commission info tests.

    This function executes all commission calculation tests for both stock
    and futures trading. It serves as the main test runner for the module.

    Args:
        main (bool, optional): Indicates whether the test is being run as the
            main program. Defaults to False. This parameter is not currently
            used but can be used for conditional behavior in the future.

    Raises:
        AssertionError: If any of the commission calculation tests fail.
    """
    check_stocks()
    check_futures()


if __name__ == "__main__":
    test_run(main=True)
