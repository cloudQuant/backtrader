#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from backtrader import Indicator
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

# 增加一些自定义的指标
from .myind import *

# Explicit exports for IDE type checking (PyCharm, etc.)
__all__ = [
    'ADX',
    'ADXR',
    'ATR',
    'AccDeOsc',
    'AccelerationDecelerationOscillator',
    'AdaptiveMovingAverage',
    'ArithmeticMean',
    'AroonIndicator',
    'AroonOsc',
    'AroonOscillator',
    'AroonUpDownOsc',
    'AroonUpDownOscillator',
    'Average',
    'AverageDirectionalMovementIndex',
    'AverageDirectionalMovementIndexRating',
    'AverageTrueRange',
    'AverageWeighted',
    'AwesomeOsc',
    'AwesomeOscillator',
    'BBands',
    'BollingerBands',
    'BollingerBandsPct',
    'CCI',
    'CommodityChannelIndex',
    'CumSum',
    'DEMA',
    'DI',
    'DM',
    'DMA',
    'DMI',
    'DPO',
    'DemarkPivotPoint',
    'DetrendedPriceOscillator',
    'DicksonMovingAverage',
    'DirectionalIndicator',
    'DirectionalMovementIndex',
    'DoubleExponentialMovingAverage',
    'EMA',
    'ExpSmoothing',
    'ExpSmoothingDynamic',
    'ExponentialMovingAverage',
    'ExponentialSmoothing',
    'ExponentialSmoothingDynamic',
    'FibonacciPivotPoint',
    'FindFirstIndex',
    'FindFirstIndexHighest',
    'FindFirstIndexLowest',
    'FindLastIndex',
    'FindLastIndexHighest',
    'FindLastIndexLowest',
    'HMA',
    'HullMovingAverage',
    'Hurst',
    'HurstExponent',
    'KAMA',
    'KST',
    'LAGF',
    'LRSI',
    'LaguerreFilter',
    'MACDHistogram',
    'MaxN',
    'MeanDev',
    'MeanDeviation',
    'MinN',
    'MinusDirectionalIndicator',
    'MomentumOsc',
    'MomentumOscillator',
    'MovingAverage',
    'MovingAverageBase',
    'MovingAverageSimple',
    'NZD',
    'Oscillator',
    'PGO',
    'PPO',
    'PPOShort',
    'PSAR',
    'ParabolicSAR',
    'PctChange',
    'PctRank',
    'PercentagePriceOscillator',
    'PercentagePriceOscillatorShort',
    'PivotPoint',
    'PlusDirectionalIndicator',
    'PrettyGoodOscillator',
    'PriceOsc',
    'PriceOscillator',
    'RMI',
    'ROC',
    'ROC100',
    'RSI',
    'RSI_Cutler',
    'RSI_EMA',
    'RSI_SMA',
    'RSI_Safe',
    'RelativeMomentumIndex',
    'RelativeStrengthIndex',
    'SMA',
    'SMMA',
    'SmoothedMovingAverage',
    'StdDev',
    'StochasticSlow',
    'TEMA',
    'TR',
    'TRIX',
    'TSI',
    'TripleExponentialMovingAverage',
    'Trix',
    'TrueRange',
    'TrueStrengthIndicator',
    'UltimateOscillator',
    'WMA',
    'WeightedAverage',
    'WeightedMovingAverage',
    'ZLEMA',
    'ZLIndicator',
    'ZeroLagExponentialMovingAverage',
    'ZeroLagIndicator',
    'haD'
]
