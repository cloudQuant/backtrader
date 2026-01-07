#!/usr/bin/env python
"""Technical Analysis Indicators Module.

This module provides a comprehensive collection of technical analysis
indicators for trading strategies. It includes moving averages,
oscillators, momentum indicators, volatility indicators, and more.

Indicator Categories:
    - Moving Averages: SMA, EMA, SMMA, WMA, DEMA, KAMA, HMA, etc.
    - Oscillators: RSI, Stochastic, MACD, CCI, etc.
    - Volatility: ATR, Bollinger Bands, Standard Deviation
    - Momentum: ROC, Momentum, Ultimate Oscillator
    - Trend: ADX, Aroon, Parabolic SAR, Ichimoku
    - Volume: OBV, Money Flow Index
    - Custom: Additional custom indicators

Example:
    Using indicators in a strategy:
    >>> class MyStrategy(bt.Strategy):
    ...     def __init__(self):
    ...         self.sma = bt.indicators.SMA(self.data.close, period=20)
    ...         self.rsi = bt.indicators.RSI(self.data.close, period=14)
"""
from ..indicator import Indicator as Indicator
from backtrader.functions import *

# The modules below should/must define __all__ with the Indicator objects
# of prepend an "_" (underscore) to private classes/variables
from .basicops import *

# base for moving averages
from .mabase import *

# moving averages (so envelope and oscillators can be auto-generated)
from .sma import *
from .ema import *
from .smma import *
from .wma import *
from .dema import *
from .kama import *
from .zlema import *
from .hma import *
from .zlind import *
from .dma import *

# depends on moving averages
from .deviation import *

# depend on basicops, moving averages and deviations
from .atr import *
from .aroon import *
from .bollinger import *
from .cci import *
from .crossover import *
from .dpo import *
from .directionalmove import *
from .envelope import *
from .heikinashi import *
from .lrsi import *
from .macd import *
from .momentum import *
from .oscillator import *
from .percentchange import *
from .percentrank import *
from .pivotpoint import *
from .prettygoodoscillator import *
from .priceoscillator import *
from .psar import *
from .rsi import *
from .stochastic import *
from .trix import *
from .tsi import *
from .ultimateoscillator import *
from .williams import *
from .rmi import *
from .awesomeoscillator import *
from .accdecoscillator import *


from .dv2 import *  # depends on percentrank

# Depends on Momentum
from .kst import *

from .ichimoku import *

from .hurst import *
from .ols import *
from .hadelta import *

# Add some custom indicators
from .myind import *

# # At the end of the file, after all imports
# from .mabase import _register_common_moving_averages
#
# # Register moving averages after all modules are loaded to avoid circular imports
# _register_common_moving_averages()
