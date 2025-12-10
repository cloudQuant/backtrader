#!/usr/bin/env python
from . import Indicator
from .sma import SMA

__all__ = ["AwesomeOscillator", "AwesomeOsc", "AO"]


# AwesomeOscillator指标
class AwesomeOscillator(Indicator):
    """
    Awesome Oscillator (AO) is a momentum indicator reflecting the precise
    changes in the market driving force, which helps to identify the trend’s
    strength up to the points of formation and reversal.


    Formula:
     - median price = (high + low) / 2
     - AO = SMA (median price, 5)- SMA (median price, 34)

    See:
      - https://www.metatrader5.com/en/terminal/help/indicators/bw_indicators/awesome
      - https://www.ifcmarkets.com/en/ntx-indicators/awesome-oscillator

    """

    # 别名
    alias = ("AwesomeOsc", "AO")
    # 要生成的line
    lines = ("ao",)
    # 参数
    params = (
        ("fast", 5),
        ("slow", 34),
        ("movav", SMA),
    )
    # 画图的参数
    plotlines = dict(ao=dict(_method="bar", alpha=0.50, width=1.0))

    # 初始化的时候，创建指标
    def __init__(self):
        # CRITICAL FIX: Call super().__init__() first to ensure self.data is set
        super().__init__()

        # 最高价和最低价的平均值
        median_price = (self.data.high + self.data.low) / 2.0
        # 计算平均值的fast个周期的平均值
        sma1 = self.p.movav(median_price, period=self.p.fast)
        # 计算平均值的slow个周期的平均值
        sma2 = self.p.movav(median_price, period=self.p.slow)
        # 计算两者的差
        self.l.ao = sma1 - sma2


AwesomeOsc = AO = AwesomeOscillator
