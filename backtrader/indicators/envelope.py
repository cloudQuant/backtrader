#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys

from . import Indicator, MovingAverage


# 装饰其他指标，给其他指标值设定了一个百分比的上下限
class EnvelopeMixIn(object):
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
    plotlines = dict(
        top=dict(_samecolor=True),
        bot=dict(_samecolor=True),
    )

    def __init__(self):
        # Mix-in and directly from object -> does not necessarily need super
        # super(EnvelopeMixIn, self).__init__()
        perc = self.p.perc / 100.0

        self.lines.top = self.lines[0] * (1.0 + perc)
        self.lines.bot = self.lines[0] * (1.0 - perc)

        super(EnvelopeMixIn, self).__init__()


# 基础类
class _EnvelopeBase(Indicator):
    lines = ("src",)

    # plot the envelope lines along the passed source
    plotinfo = dict(subplot=False)

    # Do not replot the data line
    plotlines = dict(src=dict(_plotskip=True))

    def __init__(self):
        self.lines.src = self.data
        super(_EnvelopeBase, self).__init__()


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
        if hasattr(movav.lines, '_getlinealias'):
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
                    if hasattr(movav.lines, '_get'):
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
