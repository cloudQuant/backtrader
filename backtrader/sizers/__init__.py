#!/usr/bin/env python
"""Position Sizers Module - Order size calculation strategies.

This module provides position sizer implementations that determine
the size of orders based on various strategies like fixed size,
percentage of capital, risk/reward ratios, etc.

Available Sizers:
    - FixedSize: Always uses a fixed size for orders.
    - FixedReverser: Reverses positions with fixed size.
    - PercentSizer: Uses a percentage of available cash.
    - AllInSizer: Uses all available cash for each order.
    - RiskReturnSizer: Sizes based on risk/reward ratio.

Example:
    Using a sizer with cerebro:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addsizer(bt.sizers.FixedSize, stake=100)
    >>> cerebro.addsizer(bt.sizers.PercentSizer, percents=10)
"""

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from .fixedsize import *
from .percents_sizer import *
