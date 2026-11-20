#!/usr/bin/env python
"""Envelope Indicator Module - Envelope bands around indicators.

This module provides envelope indicators that create upper and lower bands
around an indicator at a specified percentage.

Classes:
    EnvelopeMixIn: MixIn class for creating envelope bands.
    _EnvelopeBase: Base class for envelope indicators.
    Envelope: Envelope bands around data source.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma_env = bt.indicators.SMAEnvelope(self.data.close, period=20, perc=2.5)

        def next(self):
            if self.data.close[0] < self.sma_env.bot[0]:
                self.buy()
            elif self.data.close[0] > self.sma_env.top[0]:
                self.sell()
"""

import sys

from . import Indicator, MovingAverage


class PlotLineAttr:
    """Plot line attribute container for envelope visualization."""

    def __init__(self, **kwargs):
        """Initialize plot line attributes.

        Args:
            **kwargs: Arbitrary plot line attributes.
        """
        for k, v in kwargs.items():
            setattr(self, k, v)

    def _get(self, key, default=None):
        """Get attribute value for plotting system compatibility.

        Args:
            key: Attribute name to retrieve.
            default: Default value if key not found.

        Returns:
            Attribute value or default.
        """
        return getattr(self, key, default)

    def get(self, key, default=None):
        """Standard get method for compatibility.

        Args:
            key: Attribute name to retrieve.
            default: Default value if key not found.

        Returns:
            Attribute value or default.
        """
        return getattr(self, key, default)

    def __contains__(self, key):
        """Check if attribute exists.

        Args:
            key: Attribute name to check.

        Returns:
            True if attribute exists, False otherwise.
        """
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
        """Plot lines configuration object for envelope visualization."""

        def __init__(self):
            """Initialize plot lines with top and bot attributes."""
            self.top = PlotLineAttr(_samecolor=True)
            self.bot = PlotLineAttr(_samecolor=True)

        def _get(self, key, default=None):
            """Get plot line attribute for plotting system.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def __contains__(self, key):
            """Check if attribute exists.

            Args:
                key: Attribute name to check.

            Returns:
                True if attribute exists, False otherwise.
            """
            return hasattr(self, key)

    plotlines = PlotLinesObj()

    # CRITICAL FIX: Add complete plotinfo object with all required attributes
    class PlotInfoObj:
        """Plot information configuration object for envelope visualization."""

        def __init__(self):
            """Initialize plot info with default envelope settings."""
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
            """Get plot info attribute for plotting system.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def __contains__(self, key):
            """Check if attribute exists.

            Args:
                key: Attribute name to check.

            Returns:
                True if attribute exists, False otherwise.
            """
            return hasattr(self, key)

    plotinfo = PlotInfoObj()

    def __init__(self):
        """Initialize the envelope mix-in.

        Calculates percentage value for band width.
        """
        super().__init__()
        self._envelope_factor()

    def _envelope_factor(self):
        """Return the configured percentage as a multiplicative factor."""
        perc = getattr(self.p, "perc", 2.5)
        if perc is None:
            perc = 2.5

        self._perc = perc / 100.0
        return self._perc

    def _envelope_next(self, baseline):
        """Update the two bands from the current value of ``baseline``."""
        factor = self._envelope_factor()
        value = baseline[0]
        self.lines.top[0] = value * (1.0 + factor)
        self.lines.bot[0] = value * (1.0 - factor)

    def _envelope_once(self, baseline, start, end):
        """Update the band arrays for one runonce segment."""
        if start >= end:
            return

        top = self.lines.top.array
        bot = self.lines.bot.array
        values = baseline.array if hasattr(baseline, "array") else baseline
        factor = self._envelope_factor()

        while len(top) < end:
            top.append(float("nan"))
        while len(bot) < end:
            bot.append(float("nan"))

        for i in range(max(0, start), max(0, end)):
            value = values[i] if i < len(values) else float("nan")
            top[i] = value * (1.0 + factor)
            bot[i] = value * (1.0 - factor)

    def next(self):
        """Cooperatively update the base indicator and its two bands."""
        super().next()
        self._envelope_next(self.lines[0])

    def once(self, start, end):
        """Cooperatively calculate the base indicator and its bands."""
        super().once(start, end)
        self._envelope_once(self.lines[0], start, end)


# Base class
class _EnvelopeBase(Indicator):
    lines = ("src",)
    # ``EnvelopeMixIn`` is a secondary base and the parameter manager follows
    # the primary MRO branch. Declare its parameter here explicitly so
    # ``perc=`` is consumed as an indicator parameter instead of being passed
    # to this class's no-argument ``__init__``.
    params = EnvelopeMixIn.params

    # CRITICAL FIX: Add complete plotinfo object with all required attributes
    class PlotInfoObjBase:
        """Plot information configuration for envelope base class."""

        def __init__(self):
            """Initialize plot info with default settings."""
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
            """Get plot info attribute for plotting system.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def __contains__(self, key):
            """Check if attribute exists.

            Args:
                key: Attribute name to check.

            Returns:
                True if attribute exists, False otherwise.
            """
            return hasattr(self, key)

    plotinfo = PlotInfoObjBase()

    # Do not replot the data line
    # CRITICAL FIX: Convert plotlines from dict to object with _get method for plotting compatibility
    class PlotLinesObjBase:
        """Plot lines configuration for envelope base class."""

        def __init__(self):
            """Initialize plot lines with src skipped from plotting."""
            self.src = PlotLineAttr(_plotskip=True)

        def _get(self, key, default=None):
            """Get plot line attribute for plotting system.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility.

            Args:
                key: Attribute name.
                default: Default value if not found.

            Returns:
                Attribute value or default.
            """
            return getattr(self, key, default)

        def __contains__(self, key):
            """Check if attribute exists.

            Args:
                key: Attribute name to check.

            Returns:
                True if attribute exists, False otherwise.
            """
            return hasattr(self, key)

    plotlines = PlotLinesObjBase()

    def __init__(self):
        """Initialize the envelope base indicator."""
        super().__init__()
        EnvelopeMixIn._envelope_factor(self)

    def prenext(self):
        """Keep the source and bands aligned while a nested input warms up."""
        self.next()

    def next(self):
        """Copy the source value and calculate the corresponding bands."""
        self.lines.src[0] = self.data[0]
        EnvelopeMixIn._envelope_next(self, self.lines.src)

    def preonce(self, start, end):
        """Populate source and bands before a nested input reaches its period."""
        self._copy_source_once(start, end)
        EnvelopeMixIn._envelope_once(self, self.lines.src, start, end)

    def once(self, start, end):
        """Copy source values and calculate bands in runonce mode."""
        self._copy_source_once(start, end)
        EnvelopeMixIn._envelope_once(self, self.lines.src, start, end)

    def _copy_source_once(self, start, end):
        """Copy one source segment, preserving missing values as NaN."""
        if start >= end:
            return

        darray = self.data.array
        larray = self.lines.src.array

        while len(larray) < end:
            larray.append(float("nan"))

        for i in range(max(0, start), max(0, end)):
            larray[i] = darray[i] if i < len(darray) else float("nan")


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


def _make_moving_average_envelope_methods(movav):
    """Build callbacks which preserve a moving average's lifecycle methods."""

    def prenext(self):
        movav.prenext(self)
        EnvelopeMixIn._envelope_next(self, self.lines[0])

    def nextstart(self):
        movav.nextstart(self)
        EnvelopeMixIn._envelope_next(self, self.lines[0])

    def next(self):
        movav.next(self)
        EnvelopeMixIn._envelope_next(self, self.lines[0])

    def preonce(self, start, end):
        movav.preonce(self, start, end)
        EnvelopeMixIn._envelope_once(self, self.lines[0], start, end)

    def once(self, start, end):
        movav.once(self, start, end)
        EnvelopeMixIn._envelope_once(self, self.lines[0], start, end)

    return {
        "prenext": prenext,
        "nextstart": nextstart,
        "next": next,
        "preonce": preonce,
        "once": once,
    }


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
                except (AttributeError, StopIteration, TypeError, KeyError):
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
        # A secondary mixin's params are not found by the refactored
        # parameter manager unless the generated class declares them.
        "params": EnvelopeMixIn.params,
    }
    newclsdct.update(_make_moving_average_envelope_methods(movav))
    newcls = type(str(newclsname), (movav, EnvelopeMixIn), newclsdct)
    module = sys.modules[EnvelopeMixIn.__module__]
    setattr(module, newclsname, newcls)
