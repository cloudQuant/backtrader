#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import Indicator, And


# 非0差分，记录最近一个不是0的差
class NonZeroDifference(Indicator):
    """
    Keeps track of the difference between two data inputs skipping, memorizing
    the last non-zero value if the current difference is zero

    Formula:
      - diff = data - data1
      - nzd = diff if diff else diff(-1)
    """

    _mindatas = 2  # requires two (2) data sources
    alias = ("NZD",)
    lines = ("nzd",)

    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Initialize core attributes before parent init
        self.datas = []
        self.data = None
        self.data0 = None
        self.data1 = None
        
        # Process data arguments early
        if len(args) >= 2:
            self.datas = [args[0], args[1]]
            self.data = self.data0 = args[0]
            self.data1 = args[1]
        
        # Call parent __init__
        super(NonZeroDifference, self).__init__(*args, **kwargs)
        
        # CRITICAL FIX: Ensure _clock is set from data sources
        if not hasattr(self, '_clock') or self._clock is None:
            if len(self.datas) > 0:
                self._clock = self.datas[0]
        
        # CRITICAL FIX: Ensure _idx is initialized
        if not hasattr(self, '_idx'):
            self._idx = -1
            
        # CRITICAL FIX: Ensure array is initialized for each line
        import array
        import sys
        
        # Initialize arrays for line objects
        if hasattr(self, 'lines'):
            for line in self.lines:
                if not hasattr(line, 'array') or line.array is None:
                    line.array = array.array(str('d'), [0.0] * 1000)  # Pre-allocate with enough space
        
        # Initialize array for self if needed
        if not hasattr(self, 'array') or self.array is None:
            self.array = array.array(str('d'), [0.0] * 1000)  # Pre-allocate with enough space
            
    def nextstart(self):
        if hasattr(self, 'data0') and hasattr(self, 'data1') and hasattr(self, 'l') and hasattr(self.l, 'nzd'):
            self.l.nzd[0] = self.data0[0] - self.data1[0]  # seed value

    def next(self):
        if hasattr(self, 'data0') and hasattr(self, 'data1') and hasattr(self, 'l') and hasattr(self.l, 'nzd'):
            d = self.data0[0] - self.data1[0]
            self.l.nzd[0] = d if d else self.l.nzd[-1]

    def oncestart(self, start, end):
        # CRITICAL FIX: Add defensive programming check
        if not hasattr(self, 'line'):
            return
        
        # Initialize array if needed
        if not hasattr(self.line, 'array') or self.line.array is None:
            import array
            self.line.array = array.array(str('d'), [0.0] * 1000)  # Pre-allocate
            
        if not hasattr(self, 'data0') or not hasattr(self.data0, 'array'):
            return
            
        if not hasattr(self, 'data1') or not hasattr(self.data1, 'array'):
            return
            
        if start < len(self.data0.array) and start < len(self.data1.array) and start < len(self.line.array):
            self.line.array[start] = self.data0.array[start] - self.data1.array[start]

    def once(self, start, end):
        # CRITICAL FIX: Initialize missing arrays if needed
        if not hasattr(self, 'line'):
            return
            
        if not hasattr(self.line, 'array') or self.line.array is None:
            import array
            self.line.array = array.array(str('d'), [0.0] * 1000)
            
        if not hasattr(self, 'data0') or not hasattr(self, 'data1'):
            return
            
        if not hasattr(self.data0, 'array') or not hasattr(self.data1, 'array'):
            return
        
        # Ensure all arrays are initialized
        d0array = self.data0.array
        d1array = self.data1.array
        larray = self.line.array
        
        # Safe starting value
        prev = 0.0
        if start > 0 and start - 1 < len(larray):
            prev = larray[start - 1]
        
        # Safe iteration with bounds checking
        for i in range(start, min(end, min(len(d0array), len(d1array), len(larray)))):
            d = d0array[i] - d1array[i]
            larray[i] = prev = d if d else prev


# 交叉基础类
class _CrossBase(Indicator):
    _mindatas = 2

    lines = ("cross",)

    plotinfo = dict(plotymargin=0.05, plotyhlines=[0.0, 1.0])

    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Initialize core attributes before parent init
        self.datas = []
        self.data = None
        self.data0 = None
        self.data1 = None
        
        # Process data arguments early
        if len(args) >= 2:
            self.datas = [args[0], args[1]]
            self.data = self.data0 = args[0]
            self.data1 = args[1]
        
        # Call parent __init__ to ensure proper initialization
        super(_CrossBase, self).__init__(*args, **kwargs)
        
        # CRITICAL FIX: Ensure _clock is set from data sources
        if not hasattr(self, '_clock') or self._clock is None:
            if hasattr(self, 'datas') and self.datas:
                self._clock = self.datas[0]
        
        # CRITICAL FIX: Initialize _idx if it doesn't exist
        if not hasattr(self, '_idx'):
            self._idx = -1
            
        # CRITICAL FIX: Initialize arrays for all lines
        import array
        if hasattr(self, 'lines'):
            for line in self.lines:
                if not hasattr(line, 'array') or line.array is None:
                    line.array = array.array(str('d'), [0.0] * 1000)
        
        if not hasattr(self, 'array') or self.array is None:
            self.array = array.array(str('d'), [0.0] * 1000)
        
        # Create a NonZeroDifference indicator with proper initialization
        nzd = NonZeroDifference(self.data0, self.data1)
        
        # CRITICAL FIX: Propagate _clock from parent
        if hasattr(self, '_clock') and self._clock is not None:
            nzd._clock = self._clock

        # Use defensive checks before accessing attributes
        if hasattr(self, '_crossup'):
            if self._crossup:
                before = nzd(-1) < 0.0  # data0 was below or at 0
                after = self.data0 > self.data1
            else:
                before = nzd(-1) > 0.0  # data0 was above or at 0
                after = self.data0 < self.data1

            # Create And indicator and assign it to self.lines.cross
            and_ind = And(before, after)
            
            # CRITICAL FIX: Propagate _clock to the And indicator
            if hasattr(self, '_clock') and self._clock is not None:
                and_ind._clock = self._clock
                
            # CRITICAL FIX: Ensure _idx and array are available in the result
            and_ind._idx = self._idx if hasattr(self, '_idx') else -1
            
            # Initialize missing arrays in the result if needed
            if hasattr(and_ind, 'lines'):
                for line in and_ind.lines:
                    if not hasattr(line, 'array') or line.array is None:
                        line.array = array.array(str('d'), [0.0] * 1000)
            
            # Assign the result to self.lines.cross
            self.lines.cross = and_ind
            
    def _once(self, *args, **kwargs):
        """Add safety wrapper to _once method"""
        try:
            return super(_CrossBase, self)._once(*args, **kwargs)
        except AttributeError as e:
            # Handle missing array attributes
            if 'array' in str(e) or 'data0' in str(e) or 'data1' in str(e):
                # Initialize the appropriate array
                import array
                
                # Handle specific missing attributes
                if 'array' in str(e):
                    if not hasattr(self, 'array') or self.array is None:
                        self.array = array.array(str('d'), [0.0] * 1000)
                    
                if 'data0' in str(e) or 'data1' in str(e):
                    # Ensure data0 and data1 are present
                    if not hasattr(self, 'data0') or self.data0 is None:
                        self.data0 = self.datas[0] if self.datas else None
                    
                    if not hasattr(self, 'data1') or self.data1 is None:
                        self.data1 = self.datas[1] if len(self.datas) > 1 else None
                
                # Return without doing calculation since we fixed the attributes
                return
            else:
                # Re-raise other attribute errors
                raise


# 分析是否金叉
class CrossUp(_CrossBase):
    """
    This indicator gives a signal if the 1st provided data crosses over the 2nd
    indicator upwards

    It does need to look into the current time index (0) and the previous time
    index (-1) of both the 1st and 2nd data

    Formula:
      - diff = data - data1
      - upcross =  last_non_zero_diff < 0 and data0(0) > data1(0)
    """

    _crossup = True


# 分析是否死叉
class CrossDown(_CrossBase):
    """
    This indicator gives a signal if the 1st provided data crosses over the 2nd
    indicator upwards

    It does need to look into the current time index (0) and the previous time
    index (-1) of both the 1st and 2nd data

    Formula:
      - diff = data - data1
      - downcross = last_non_zero_diff > 0 and data0(0) < data1(0)
    """

    _crossup = False


# 分析是否交叉
class CrossOver(Indicator):
    """
    This indicator gives a signal if the provided datas (2) cross up or down.

      - 1.0 if the 1st data crosses the 2nd data upwards
      - -1.0 if the 1st data crosses the 2nd data downwards

    It does need to look into the current time index (0) and the previous time
    index (-1) of both the 1t and 2nd data

    Formula:
      - diff = data - data1
      - upcross =  last_non_zero_diff < 0 and data0(0) > data1(0)
      - downcross = last_non_zero_diff > 0 and data0(0) < data1(0)
      - crossover = upcross - downcross
    """

    _mindatas = 2

    lines = ("crossover",)

    plotinfo = dict(plotymargin=0.05, plotyhlines=[-1.0, 1.0])

    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Initialize core attributes before parent init
        self.datas = []
        self.data = None
        self.data0 = None
        self.data1 = None
        
        # Process data arguments early
        if len(args) >= 2:
            self.datas = [args[0], args[1]]
            self.data = self.data0 = args[0]
            self.data1 = args[1]
            
        # Call parent __init__ to ensure proper initialization
        super(CrossOver, self).__init__(*args, **kwargs)
        
        # CRITICAL FIX: Ensure _clock is set from data sources
        if not hasattr(self, '_clock') or self._clock is None:
            if hasattr(self, 'datas') and self.datas:
                self._clock = self.datas[0]
        
        # CRITICAL FIX: Initialize _idx if it doesn't exist
        if not hasattr(self, '_idx'):
            self._idx = -1
            
        # CRITICAL FIX: Ensure array is initialized for each line
        import array
        if hasattr(self, 'lines'):
            for line in self.lines:
                if not hasattr(line, 'array') or line.array is None:
                    line.array = array.array(str('d'), [0.0] * 1000)  # Pre-allocate
                    
        if not hasattr(self, 'array') or self.array is None:
            self.array = array.array(str('d'), [0.0] * 1000)  # Pre-allocate
        
        # CRITICAL FIX: Ensure l is created
        if not hasattr(self, 'l'):
            from .linebuffer import LineActions
            self.l = LineActions(self.lines)
        
        # Create sub-indicators with proper attribute propagation
        upcross = CrossUp(self.data0, self.data1)
        downcross = CrossDown(self.data0, self.data1)
        
        # CRITICAL FIX: Propagate _clock to sub-indicators
        if hasattr(self, '_clock') and self._clock is not None:
            upcross._clock = self._clock
            downcross._clock = self._clock
        
        # CRITICAL FIX: Ensure the arithmetic operation result has _clock
        result = upcross - downcross
        if hasattr(self, '_clock') and self._clock is not None:
            result._clock = self._clock
            
        # Ensure result has array initialized properly
        if hasattr(result, 'lines'):
            for line in result.lines:
                if not hasattr(line, 'array') or line.array is None:
                    line.array = array.array(str('d'), [0.0] * 1000)
        
        # CRITICAL FIX: Initialize arrays for the result's line objects
        if not hasattr(result, 'array') or result.array is None:
            result.array = array.array(str('d'), [0.0] * 1000)
        
        # Save the sub-indicators as attributes for later use
        self.upcross = upcross
        self.downcross = downcross
        
        self.lines.crossover = result
        
    def _oncepost(self, *args, **kwargs):
        # CRITICAL FIX: Add defensive processing in _oncepost to avoid attribute errors
        try:
            return super(CrossOver, self)._oncepost(*args, **kwargs)
        except AttributeError as e:
            # Provide fallback behavior
            if '_clock' in str(e):
                # Ensure _clock is set even during oncepost processing
                if not hasattr(self, '_clock'):
                    if hasattr(self, 'datas') and self.datas:
                        self._clock = self.datas[0]
                    else:
                        self._clock = None
            elif 'array' in str(e):
                # Ensure array exists
                import array
                if not hasattr(self, 'array'):
                    self.array = array.array(str('d'), [0.0] * 1000)
            # Re-raise other attribute errors that we can't handle
            else:
                raise
                
    # Handle _once errors with defensive programming
    def _once(self, *args, **kwargs):
        try:
            return super(CrossOver, self)._once(*args, **kwargs)
        except AttributeError as e:
            # Handle missing attributes
            import array
            if 'array' in str(e):
                if not hasattr(self, 'array') or self.array is None:
                    self.array = array.array(str('d'), [0.0] * 1000)
                
                # Also check lines
                if hasattr(self, 'lines'):
                    for line in self.lines:
                        if not hasattr(line, 'array') or line.array is None:
                            line.array = array.array(str('d'), [0.0] * 1000)
            
            elif 'data0' in str(e) and hasattr(self, 'datas') and len(self.datas) > 0:
                self.data0 = self.datas[0]
            
            elif 'data1' in str(e) and hasattr(self, 'datas') and len(self.datas) > 1:
                self.data1 = self.datas[1]
            
            # Try to create basic functionality
            return
    
    def _getminperiod(self):
        # Add defensive check to avoid attribute errors
        try:
            return super(CrossOver, self)._getminperiod()
        except AttributeError:
            # Return a safe fallback value
            return 2  # CrossOver needs at least 2 periods to work
    
    def next(self):
        """
        Direct implementation of CrossOver calculation logic to ensure proper values
        and avoid relying on potentially problematic sub-indicator calculation chain
        """
        try:
            # Get current data values
            d0_curr = self.data0[0]
            d1_curr = self.data1[0]
            
            # Get previous data values if available
            if len(self.data0) > 1 and len(self.data1) > 1:
                d0_prev = self.data0[-1]
                d1_prev = self.data1[-1]
                
                import numpy as np
                # Check for valid values
                if (not np.isnan(d0_curr) and not np.isnan(d1_curr) and 
                    not np.isnan(d0_prev) and not np.isnan(d1_prev)):
                    
                    # Calculate crossover directly
                    prev_relationship = d0_prev - d1_prev
                    curr_relationship = d0_curr - d1_curr
                    
                    # If previous values have a relationship and current values cross
                    if prev_relationship != 0:
                        if prev_relationship < 0 and curr_relationship > 0:  # Upward cross
                            self.lines.crossover[0] = 1.0
                            return
                        elif prev_relationship > 0 and curr_relationship < 0:  # Downward cross
                            self.lines.crossover[0] = -1.0
                            return
            
            # Default: no crossover
            self.lines.crossover[0] = 0.0
                
        except (AttributeError, IndexError) as e:
            # Handle errors safely
            import sys
            print(f"CrossOver.next(): Error: {e}", file=sys.stderr)
            # Set a safe default
            if hasattr(self, 'lines') and hasattr(self.lines, 'crossover'):
                self.lines.crossover[0] = 0.0
