#!/usr/bin/env python
import sys

from . import Indicator, MovingAverage


# CRITICAL FIX: Define PlotLineAttr class before using it
class PlotLineAttr:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def _get(self, key, default=None):
        """CRITICAL: _get method expected by plotting system"""
        return getattr(self, key, default)

    def get(self, key, default=None):
        """Standard get method for compatibility"""
        return getattr(self, key, default)

    def __contains__(self, key):
        return hasattr(self, key)


# Decorate other indicators, set upper and lower percentage limits for indicator values
class EnvelopeMixIn:
    """
    MixIn class to create a subclass with another indicator. The main line of
    that indicator will be surrounded by an upper and lower band separated a
    given "percentage" from the input main line

    The usage is:

      - Class XXXEnvelope(XXX, EnvelopeMixIn)

    Formula:
      - 'line' (inherited from XXX)
      - top = 'line' * (1 + perc)
      - bot = 'line' * (1 - perc)

    See also:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:moving_average_envelopes
    """

    lines = (
        "top",
        "bot",
    )
    params = (("perc", 2.5),)

    # CRITICAL FIX: Convert plotlines from dict to object with _get method for plotting compatibility
    class PlotLinesObj:
        def __init__(self):
            self.top = PlotLineAttr(_samecolor=True)
            self.bot = PlotLineAttr(_samecolor=True)

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            return getattr(self, key, default)

        def __contains__(self, key):
            return hasattr(self, key)

    plotlines = PlotLinesObj()

    # CRITICAL FIX: Add complete plotinfo object with all required attributes
    class PlotInfoObj:
        def __init__(self):
            self.subplot = False
            self.plot = True
            self.plotname = ""
            self.plotskip = False
            self.plotabove = False
            self.plotlinelabels = False
            self.plotlinevalues = True
            self.plotvaluetags = True
            self.plotymargin = 0.0
            self.plotyhlines = []
            self.plotyticks = []
            self.plothlines = []
            self.plotforce = False
            self.plotmaster = None
            self.legendloc = None  # CRITICAL: Add the missing legendloc attribute

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            return getattr(self, key, default)

        def __contains__(self, key):
            return hasattr(self, key)

    plotinfo = PlotInfoObj()

    def __init__(self):
        # CRITICAL FIX: Call super().__init__() first to ensure params and lines are initialized
        super().__init__()

        # Now we can safely use self.p.perc and self.lines[0]
        # Check if perc parameter exists, use default if not
        perc_value = getattr(self.p, "perc", 2.5)
        if perc_value is None:
            perc_value = 2.5
        self._perc = perc_value / 100.0

    def next(self):
        base_val = self.lines[0][0]
        self.lines.top[0] = base_val * (1.0 + self._perc)
        self.lines.bot[0] = base_val * (1.0 - self._perc)

    def once(self, start, end):
        import math
        base_array = self.lines[0].array
        top_array = self.lines.top.array
        bot_array = self.lines.bot.array
        perc = self._perc
        
        for arr in [top_array, bot_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        for i in range(start, min(end, len(base_array))):
            base_val = base_array[i] if i < len(base_array) else 0.0
            if isinstance(base_val, float) and math.isnan(base_val):
                top_array[i] = float("nan")
                bot_array[i] = float("nan")
            else:
                top_array[i] = base_val * (1.0 + perc)
                bot_array[i] = base_val * (1.0 - perc)


# 基础类
class _EnvelopeBase(Indicator):
    lines = ("src",)

    # CRITICAL FIX: Add complete plotinfo object with all required attributes
    class PlotInfoObjBase:
        def __init__(self):
            self.subplot = False
            self.plot = True
            self.plotname = ""
            self.plotskip = False
            self.plotabove = False
            self.plotlinelabels = False
            self.plotlinevalues = True
            self.plotvaluetags = True
            self.plotymargin = 0.0
            self.plotyhlines = []
            self.plotyticks = []
            self.plothlines = []
            self.plotforce = False
            self.plotmaster = None
            self.legendloc = None  # CRITICAL: Add the missing legendloc attribute

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            return getattr(self, key, default)

        def __contains__(self, key):
            return hasattr(self, key)

    plotinfo = PlotInfoObjBase()

    # Do not replot the data line
    # CRITICAL FIX: Convert plotlines from dict to object with _get method for plotting compatibility
    class PlotLinesObjBase:
        def __init__(self):
            self.src = PlotLineAttr(_plotskip=True)

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            return getattr(self, key, default)

        def __contains__(self, key):
            return hasattr(self, key)

    plotlines = PlotLinesObjBase()

    def __init__(self):
        super().__init__()

    def next(self):
        self.lines.src[0] = self.data[0]

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.src.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(start, min(end, len(darray))):
            larray[i] = darray[i] if i < len(darray) else 0.0


class Envelope(_EnvelopeBase, EnvelopeMixIn):
    """
    It creates envelope bands separated from the source data by a given
    percentage

    Formula:
      - src = datasource
      - top = src * (1 + perc)
      - bot = src * (1 - perc)

    See also:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:moving_average_envelopes
    """


# Automatic creation of Moving Average Envelope classes

for movav in MovingAverage._movavs[0:]:
    _newclsdoc = """
    %s and envelope bands separated "perc" from it

    Formula:
      - %s (from %s)
      - top = %s * (1 + perc)
      - bot = %s * (1 - perc)

    See also:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:moving_average_envelopes
    """
    # Skip aliases - they will be created automatically
    if getattr(movav, "aliased", ""):
        continue

    movname = movav.__name__
    # Handle both tuple lines and Lines objects after refactoring
    try:
        if hasattr(movav.lines, "_getlinealias"):
            # It's a Lines object
            linename = movav.lines._getlinealias(0)
        elif isinstance(movav.lines, (tuple, list)) and movav.lines:
            # It's a tuple/list of line names
            linename = movav.lines[0]
        elif isinstance(movav.lines, dict):
            # It's a dictionary - extract first key as line name
            if movav.lines:
                try:
                    # Handle the case when trying to access _get on dict object
                    if hasattr(movav.lines, "_get"):
                        linename = movav.lines._get(0)
                    else:
                        # Use first key in the dictionary
                        linename = next(iter(movav.lines))
                except Exception:
                    # Fallback to the lower case name of the class
                    linename = movav.__name__.lower()
            else:
                linename = movav.__name__.lower()
        else:
            # Fallback to first line name or class name
            linename = movav.__name__.lower()
    except (AttributeError, IndexError, KeyError, TypeError):
        # Ultimate fallback - use class name if all else fails
        linename = movav.__name__.lower()

    newclsname = movname + "Envelope"

    newaliases = []
    for alias in getattr(movav, "alias", []):
        for suffix in ["Envelope"]:
            newaliases.append(alias + suffix)

    newclsdoc = _newclsdoc % (movname, linename, movname, linename, linename)

    newclsdct = {
        "__doc__": newclsdoc,
        "__module__": EnvelopeMixIn.__module__,
        "_notregister": True,
        "alias": newaliases,
    }
    newcls = type(str(newclsname), (movav, EnvelopeMixIn), newclsdct)
    module = sys.modules[EnvelopeMixIn.__module__]
    setattr(module, newclsname, newcls)
