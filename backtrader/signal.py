#!/usr/bin/env python
"""Signal Module - Signal indicator for trading strategies.

This module provides the Signal indicator which wraps a data line
to provide trading signal values for strategy execution.

Constants:
    SIGNAL_NONE: No signal.
    SIGNAL_LONGSHORT: Both long and short signals.
    SIGNAL_LONG: Long entry signal.
    SIGNAL_LONG_INV: Inverted long signal.
    SIGNAL_LONG_ANY: Any long signal variant.
    SIGNAL_SHORT: Short entry signal.
    SIGNAL_SHORT_INV: Inverted short signal.
    SIGNAL_SHORT_ANY: Any short signal variant.
    SIGNAL_LONGEXIT: Long exit signal.
    SIGNAL_LONGEXIT_INV: Inverted long exit signal.
    SIGNAL_LONGEXIT_ANY: Any long exit variant.
    SIGNAL_SHORTEXIT: Short exit signal.
    SIGNAL_SHORTEXIT_INV: Inverted short exit signal.
    SIGNAL_SHORTEXIT_ANY: Any short exit variant.

Classes:
    Signal: Indicator that wraps a data line as a trading signal.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> signal = bt.Signal(data)
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.SMA, period=20)
"""
from .indicator import Indicator

# Create different SIGNAL types
(
    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_INV,
    SIGNAL_SHORTEXIT_ANY,
) = range(14)

# Different signal types
SignalTypes = [
    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_INV,
    SIGNAL_SHORTEXIT_ANY,
]


# Inherit from Indicator, create a signal indicator
class Signal(Indicator):
    """Signal indicator for trading strategies.

    The Signal class wraps a data line to provide trading signal values
    for strategy execution. It inherits from Indicator and exposes a
    single signal line that can be used to generate long/short signals.

    Attributes:
        SignalTypes: List of available signal type constants.
        lines: Tuple containing the signal line name.

    Example:
        >>> signal = bt.Signal(data)
        >>> cerebro.adddata(data)
    """

    # Signal type
    SignalTypes = SignalTypes
    # Create a signal line
    lines = ("signal",)

    # Initialize
    def __init__(self):
        """Initialize the Signal indicator.

        Wraps the first data line from data0 as the signal line and sets
        up plotting information to use data0's clock as the plot master.
        """
        self.lines.signal = self.data0.lines[0]
        self.plotinfo.plotmaster = getattr(self.data0, "_clock", self.data0)
