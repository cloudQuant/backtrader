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

"""Test module for verifying metaclass and parameter inheritance functionality.

This module tests the correct behavior of the `frompackages` directive when used
with inheritance. It verifies that classes inheriting from a base class that uses
the `frompackages` import mechanism maintain proper functionality without breaking
parameter access or initialization.

The test addresses a bug where inheriting from a base class with `frompackages`
would cause issues with parameter resolution. For more details, see:
https://community.backtrader.com/topic/2661/frompackages-directive-functionality-seems-to-be-broken-when-using-inheritance
"""

import backtrader as bt

import testcommon


class RunFrompackages(testcommon.SampleParamsHolder):
    """Test class for verifying frompackages functionality with inheritance.

    This class tests that inheriting from a base class that uses the `frompackages`
    import mechanism does not break the functionality of the base class. It inherits
    from SampleParamsHolder which uses the `frompackages` directive to import the
    `factorial` function from the math module.

    Attributes:
        frompackages: Tuple defining packages and symbols to import parameters from.
            Inherited from SampleParamsHolder.
        range (int): Calculated factorial value (factorial of 10).
            Inherited from SampleParamsHolder.
    """

    def __init__(self):
        """Initialize the RunFrompackages test instance.

        Initializes the parent class (SampleParamsHolder) which sets up the
        `frompackages` directive and calculates the factorial value for testing.

        The initialization verifies that the `frompackages` mechanism works
        correctly through inheritance, allowing access to imported symbols
        (like `factorial` from the math module) in the child class.
        """
        super().__init__()
        # Prepare the lags array


def test_run(main=False):
    """Test function to verify frompackages functionality with inheritance.

    This function instantiates the RunFrompackages class and verifies that no
    exception is raised during initialization. The test confirms that the
    `frompackages` directive works correctly when a child class inherits from
    a base class that uses this mechanism.

    The test addresses a bug where using `frompackages` in a base class would
    break functionality when inherited by child classes. For more details on
    the bug discussion, see:
    https://community.backtrader.com/topic/2661/frompackages-directive-functionality-seems-to-be-broken-when-using-inheritance

    Args:
        main (bool, optional): If True, indicates the test is being run as the
            main script. Defaults to False. This parameter is currently not
            used but is kept for compatibility with the test framework.

    Returns:
        None: This function does not return a value. It performs a simple
            instantiation test that should complete without raising exceptions.

    Raises:
        Exception: Any exception raised during RunFrompackages instantiation
            indicates a failure in the frompackages inheritance mechanism.
    """
    test = RunFrompackages()


if __name__ == "__main__":
    test_run(main=True)
