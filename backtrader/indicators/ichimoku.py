#!/usr/bin/env python
import math
from . import Highest, Indicator, Lowest


# 日本云图指标
class Ichimoku(Indicator):
    """
    Developed and published in his book in 1969 by journalist Goichi Hosoda

    Formula:
      - tenkan_sen = (Highest (High, tenkan) + Lowest (Low, tenkan)) / 2.0
      - kijun_sen = (Highest (High, kijun) + Lowest (Low, kijun)) / 2.0

      The next 2 are pushed 26 bars into the future

      - senkou_span_a = (tenkan_sen + kijun_sen) / 2.0
      - senkou_span_b = ((Highest (High, senkou) + Lowest (Low, senkou)) / 2.0

      This is pushed 26 bars into the past

      - chikou = close

    The cloud (Kumo) is formed by the area between the senkou_spans

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:ichimoku_cloud

    """

    lines = (
        "tenkan_sen",
        "kijun_sen",
        "senkou_span_a",
        "senkou_span_b",
        "chikou_span",
    )
    params = (
        ("tenkan", 9),
        ("kijun", 26),
        ("senkou", 52),
        ("senkou_lead", 26),  # forward push
        ("chikou", 26),  # backwards push
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        senkou_span_a=dict(_fill_gt=("senkou_span_b", "g"), _fill_lt=("senkou_span_b", "r")),
    )

    def __init__(self):
        super().__init__()
        
        # Create sub-indicators and store references for explicit computation
        self.hi_tenkan = Highest(self.data.high, period=self.p.tenkan)
        self.lo_tenkan = Lowest(self.data.low, period=self.p.tenkan)
        
        self.hi_kijun = Highest(self.data.high, period=self.p.kijun)
        self.lo_kijun = Lowest(self.data.low, period=self.p.kijun)
        
        self.hi_senkou = Highest(self.data.high, period=self.p.senkou)
        self.lo_senkou = Lowest(self.data.low, period=self.p.senkou)
        
        # Calculate minperiod - need senkou_lead bars of history for the forward shift
        self._minperiod = max(self._minperiod, self.p.senkou + self.p.senkou_lead)
        
        # Propagate minperiod to lines
        for line in self.lines:
            line.updateminperiod(self._minperiod)

    def next(self):
        # Calculate tenkan_sen and kijun_sen
        idx = self.lines[0].idx
        
        hi_tenkan_val = self.hi_tenkan.lines[0].array[idx]
        lo_tenkan_val = self.lo_tenkan.lines[0].array[idx]
        tenkan_val = (hi_tenkan_val + lo_tenkan_val) / 2.0
        self.lines.tenkan_sen[0] = tenkan_val
        
        hi_kijun_val = self.hi_kijun.lines[0].array[idx]
        lo_kijun_val = self.lo_kijun.lines[0].array[idx]
        kijun_val = (hi_kijun_val + lo_kijun_val) / 2.0
        self.lines.kijun_sen[0] = kijun_val
        
        # senkou_span_a: (tenkan + kijun) / 2, shifted forward by senkou_lead
        # At current bar, we display the value calculated senkou_lead bars ago
        shift = self.p.senkou_lead
        if idx >= shift:
            past_idx = idx - shift
            past_hi_tenkan = self.hi_tenkan.lines[0].array[past_idx]
            past_lo_tenkan = self.lo_tenkan.lines[0].array[past_idx]
            past_tenkan = (past_hi_tenkan + past_lo_tenkan) / 2.0
            past_hi_kijun = self.hi_kijun.lines[0].array[past_idx]
            past_lo_kijun = self.lo_kijun.lines[0].array[past_idx]
            past_kijun = (past_hi_kijun + past_lo_kijun) / 2.0
            self.lines.senkou_span_a[0] = (past_tenkan + past_kijun) / 2.0
        else:
            self.lines.senkou_span_a[0] = float('nan')
        
        # senkou_span_b: (hi_senkou + lo_senkou) / 2, shifted forward by senkou_lead
        if idx >= shift:
            past_idx = idx - shift
            past_hi_senkou = self.hi_senkou.lines[0].array[past_idx]
            past_lo_senkou = self.lo_senkou.lines[0].array[past_idx]
            self.lines.senkou_span_b[0] = (past_hi_senkou + past_lo_senkou) / 2.0
        else:
            self.lines.senkou_span_b[0] = float('nan')
        
        # chikou_span: close shifted backward (displayed chikou bars in the past)
        # When accessing chikou_span[0], we get current close (it will be plotted chikou bars back)
        self.lines.chikou_span[0] = self.data.close[0]

    def once(self, start, end):
        """Calculate Ichimoku in runonce mode"""
        # Get arrays from sub-indicators
        hi_tenkan_arr = self.hi_tenkan.lines[0].array
        lo_tenkan_arr = self.lo_tenkan.lines[0].array
        hi_kijun_arr = self.hi_kijun.lines[0].array
        lo_kijun_arr = self.lo_kijun.lines[0].array
        hi_senkou_arr = self.hi_senkou.lines[0].array
        lo_senkou_arr = self.lo_senkou.lines[0].array
        close_arr = self.data.close.array
        
        # Get output arrays
        tenkan_arr = self.lines.tenkan_sen.array
        kijun_arr = self.lines.kijun_sen.array
        senkou_a_arr = self.lines.senkou_span_a.array
        senkou_b_arr = self.lines.senkou_span_b.array
        chikou_arr = self.lines.chikou_span.array
        
        # Ensure output arrays are sized
        for arr in [tenkan_arr, kijun_arr, senkou_a_arr, senkou_b_arr, chikou_arr]:
            while len(arr) < end:
                arr.append(float('nan'))
        
        shift = self.p.senkou_lead
        
        for i in range(start, min(end, len(hi_tenkan_arr), len(lo_tenkan_arr))):
            # tenkan_sen
            hi_t = hi_tenkan_arr[i]
            lo_t = lo_tenkan_arr[i]
            if hi_t is not None and lo_t is not None:
                if not (isinstance(hi_t, float) and math.isnan(hi_t)) and \
                   not (isinstance(lo_t, float) and math.isnan(lo_t)):
                    tenkan_arr[i] = (hi_t + lo_t) / 2.0
                else:
                    tenkan_arr[i] = float('nan')
            else:
                tenkan_arr[i] = float('nan')
            
            # kijun_sen
            if i < len(hi_kijun_arr) and i < len(lo_kijun_arr):
                hi_k = hi_kijun_arr[i]
                lo_k = lo_kijun_arr[i]
                if hi_k is not None and lo_k is not None:
                    if not (isinstance(hi_k, float) and math.isnan(hi_k)) and \
                       not (isinstance(lo_k, float) and math.isnan(lo_k)):
                        kijun_arr[i] = (hi_k + lo_k) / 2.0
                    else:
                        kijun_arr[i] = float('nan')
                else:
                    kijun_arr[i] = float('nan')
            
            # senkou_span_a: shifted forward by senkou_lead
            # Value at index i is calculated from index (i - shift)
            past_idx = i - shift
            if past_idx >= 0 and past_idx < len(hi_tenkan_arr) and past_idx < len(lo_tenkan_arr) \
               and past_idx < len(hi_kijun_arr) and past_idx < len(lo_kijun_arr):
                past_hi_t = hi_tenkan_arr[past_idx]
                past_lo_t = lo_tenkan_arr[past_idx]
                past_hi_k = hi_kijun_arr[past_idx]
                past_lo_k = lo_kijun_arr[past_idx]
                
                valid = True
                for v in [past_hi_t, past_lo_t, past_hi_k, past_lo_k]:
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        valid = False
                        break
                
                if valid:
                    past_tenkan = (past_hi_t + past_lo_t) / 2.0
                    past_kijun = (past_hi_k + past_lo_k) / 2.0
                    senkou_a_arr[i] = (past_tenkan + past_kijun) / 2.0
                else:
                    senkou_a_arr[i] = float('nan')
            else:
                senkou_a_arr[i] = float('nan')
            
            # senkou_span_b: shifted forward by senkou_lead
            if past_idx >= 0 and past_idx < len(hi_senkou_arr) and past_idx < len(lo_senkou_arr):
                past_hi_s = hi_senkou_arr[past_idx]
                past_lo_s = lo_senkou_arr[past_idx]
                
                if past_hi_s is not None and past_lo_s is not None:
                    if not (isinstance(past_hi_s, float) and math.isnan(past_hi_s)) and \
                       not (isinstance(past_lo_s, float) and math.isnan(past_lo_s)):
                        senkou_b_arr[i] = (past_hi_s + past_lo_s) / 2.0
                    else:
                        senkou_b_arr[i] = float('nan')
                else:
                    senkou_b_arr[i] = float('nan')
            else:
                senkou_b_arr[i] = float('nan')
            
            # chikou_span: current close (will be plotted shifted back)
            if i < len(close_arr):
                chikou_arr[i] = close_arr[i]
            else:
                chikou_arr[i] = float('nan')
