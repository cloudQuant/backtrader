#!/usr/bin/env python
import math
from . import Indicator
from .sma import SMA

__all__ = ["AwesomeOscillator", "AwesomeOsc", "AO"]


# AwesomeOscillator指标
class AwesomeOscillator(Indicator):
    """
    Awesome Oscillator (AO) is a momentum indicator reflecting the precise
    changes in the market driving force, which helps to identify the trend's
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
        super().__init__()
        self.addminperiod(self.p.slow)

    def next(self):
        fast = self.p.fast
        slow = self.p.slow
        
        # Calculate median price SMA for fast period
        fast_sum = 0.0
        for i in range(fast):
            fast_sum += (self.data.high[-i] + self.data.low[-i]) / 2.0
        sma_fast = fast_sum / fast
        
        # Calculate median price SMA for slow period
        slow_sum = 0.0
        for i in range(slow):
            slow_sum += (self.data.high[-i] + self.data.low[-i]) / 2.0
        sma_slow = slow_sum / slow
        
        self.lines.ao[0] = sma_fast - sma_slow

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        larray = self.lines.ao.array
        fast = self.p.fast
        slow = self.p.slow
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(min(slow - 1, len(high_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(slow - 1, min(end, len(high_array), len(low_array))):
            # Calculate fast SMA
            fast_sum = 0.0
            for j in range(fast):
                idx = i - j
                if idx >= 0:
                    fast_sum += (high_array[idx] + low_array[idx]) / 2.0
            sma_fast = fast_sum / fast
            
            # Calculate slow SMA
            slow_sum = 0.0
            for j in range(slow):
                idx = i - j
                if idx >= 0:
                    slow_sum += (high_array[idx] + low_array[idx]) / 2.0
            sma_slow = slow_sum / slow
            
            larray[i] = sma_fast - sma_slow


AwesomeOsc = AO = AwesomeOscillator
