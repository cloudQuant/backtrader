#!/usr/bin/env python
"""Fixed Size Sizer Module - Fixed stake position sizing.

This module provides the FixedSize sizer for using a fixed stake
size in trading operations.

Classes:
    FixedSize: Returns a fixed stake size for orders.

Example:
    >>> cerebro.addsizer(bt.sizers.FixedSize, stake=10)
"""

from ..parameters import Int, ParameterDescriptor
from ..sizer import Sizer


class FixedSize(Sizer):
    """
    This sizer simply returns a fixed size for any operation.
    Size can be controlled by the number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.

    This class has been refactored from legacy params tuple to the new
    ParameterDescriptor system for Day 36-38 of the metaprogramming removal project.

    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    """

    # Use new parameter descriptor system to define parameters
    stake = ParameterDescriptor(
        default=1, type_=int, validator=Int(min_val=1), doc="Fixed stake size for operations"
    )
    tranches = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Number of tranches to divide stake into",
    )

    def __init__(self, **kwargs):
        """Initialize the FixedSize sizer.

        Args:
            **kwargs: Keyword arguments for sizer configuration including
                stake and tranches parameters.
        """
        super().__init__(**kwargs)

    # Return specific stake size, if tranches > 1, will divide stake into tranches parts, otherwise return stake directly
    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.get_param("tranches") > 1:
            return abs(int(self.get_param("stake") / self.get_param("tranches")))
        else:
            return self.get_param("stake")

    # Set stake size
    def setsizing(self, stake):
        """Set the fixed stake size for operations.

        Args:
            stake (int): The stake size to set. If tranches > 1, this value
                will be divided by tranches and stored as the internal stake.
        """
        if self.get_param("tranches") > 1:
            self.set_param("stake", abs(int(stake / self.get_param("tranches"))))
        else:
            self.set_param("stake", stake)  # OLD METHOD FOR SAMPLE COMPATIBILITY


# Another name for FixedSize
SizerFix = FixedSize


# If opening position, use stake, if reversing position, use double stake
class FixedReverser(Sizer):
    """This sizer returns the needes fixed size to reverse an open position or
    the fixed size to open one

      - To open a position: return the param ``stake``

      - To reverse a position: return 2 * `stake`

    Params:
      - ``stake`` (default: ``1``)
    """

    stake = ParameterDescriptor(
        default=1, type_=int, validator=Int(min_val=1), doc="Fixed stake size for operations"
    )

    def __init__(self, **kwargs):
        """Initialize the FixedReverser sizer.

        Args:
            **kwargs: Keyword arguments for sizer configuration including
                stake parameter.
        """
        super().__init__(**kwargs)

    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.strategy.getposition(data)
        size = self.get_param("stake") * (1 + (position.size != 0))
        return size


# Fixed target stake size, if tranches > 1, first divide stake into tranches parts, then calculate current position and each part vs stake, choose smaller as order size
# If tranches <= 1, directly use stake size
class FixedSizeTarget(Sizer):
    """
    This sizer simply returns a fixed target size, useful when coupled
    with Target Orders and specifically ``cerebro.target_order_size()``.
    Size can be controlled by the number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.

    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    """

    stake = ParameterDescriptor(
        default=1, type_=int, validator=Int(min_val=1), doc="Fixed target stake size"
    )
    tranches = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Number of tranches to divide stake into",
    )

    def __init__(self, **kwargs):
        """Initialize the FixedSizeTarget sizer.

        Args:
            **kwargs: Keyword arguments for sizer configuration including
                stake and tranches parameters.
        """
        super().__init__(**kwargs)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.get_param("tranches") > 1:
            size = abs(int(self.get_param("stake") / self.get_param("tranches")))
            return min((self.strategy.position.size + size), self.get_param("stake"))
        else:
            return self.get_param("stake")

    def setsizing(self, stake):
        """Set the fixed target stake size for operations.

        Args:
            stake (int): The target stake size to set. If tranches > 1, this value
                will be divided by tranches and adjusted based on current
                position size to reach the target.
        """
        if self.get_param("tranches") > 1:
            size = abs(int(stake / self.get_param("tranches")))
            self.set_param("stake", min((self.strategy.position.size + size), stake))
        else:
            self.set_param("stake", stake)  # OLD METHOD FOR SAMPLE COMPATIBILITY
