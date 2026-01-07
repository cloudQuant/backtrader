#!/usr/bin/env python
"""Percent Sizer Module - Percentage-based position sizing.

This module provides sizers that calculate position size based on
a percentage of available cash.

Classes:
    PercentSizer: Uses percentage of cash for sizing.
    AllInSizer: Uses 100% of available cash.
    PercentSizerInt: PercentSizer returning int values.
    AllInSizerInt: AllInSizer returning int values.

Example:
    >>> cerebro.addsizer(bt.sizers.PercentSizer, percents=20)
"""
from ..parameters import Float, ParameterDescriptor
from ..sizer import Sizer

__all__ = ["PercentSizer", "AllInSizer", "PercentSizerInt", "AllInSizerInt"]
class PercentSizer(Sizer):
    """This sizer return percentages of available cash

    This class has been refactored from legacy params tuple to the new
    ParameterDescriptor system for Day 36-38 of the metaprogramming removal project.

    Params:
      - ``percents`` (default: ``20``)
      - ``retint`` (default: ``False``) return an int size or rather the float value
    """

    # Use new parameter descriptor system to define parameters
    percents = ParameterDescriptor(
        default=20,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use",
    )
    retint = ParameterDescriptor(
        default=False, type_=bool, doc="Return an int size or rather the float value"
    )

    def __init__(self, **kwargs):
        """Initialize the PercentSizer sizer.

        Args:
            **kwargs: Keyword arguments for sizer configuration.
        """
        super().__init__(**kwargs)

    # If no current position, calculate orderable quantity based on cash percentage
    # If current position exists, directly use position size as order stake
    # If need to convert to int, then convert to int
    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.broker.getposition(data)
        if not position:
            size = cash / data.close[0] * (self.get_param("percents") / 100)
        else:
            size = position.size

        if self.get_param("retint"):
            size = int(size)

        return size


# Use all available cash to place order
class AllInSizer(PercentSizer):
    """This sizer return all available cash of broker

    Params:
      - ``percents`` (default: ``100``)
    """

    # Redefine default value of percents parameter
    percents = ParameterDescriptor(
        default=100,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use (100% for all-in)",
    )


# Calculate order stake by percentage, then round to integer
class PercentSizerInt(PercentSizer):
    """This sizer return percentages of available cash in the form of size truncated
    to an int

    Params:
      - ``percents`` (default: ``20``)
    """

    # Redefine default value of retint parameter
    retint = ParameterDescriptor(
        default=True, type_=bool, doc="Return an int size or rather the float value (True for int)"
    )


# Place order based on all available cash, stake must be rounded
class AllInSizerInt(PercentSizerInt):
    """This sizer returns all available cash of broker with the
    size truncated to an int

     Params:
       - ``percents`` (default: ``100``)
    """

    # Redefine default value of percents parameter
    percents = ParameterDescriptor(
        default=100,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use (100% for all-in)",
    )
