#!/usr/bin/env python
"""Plot Utils Module - Plotting utility functions.

This module provides utility functions for plotting, including
box styling and color manipulation.

Functions:
    tag_box_style: Create a box path with a tab/pointer.
    color_by_alpha: Modify color alpha channel.
    clip_obj: Clip object to visible area.

Example:
    Creating a box style:
    >>> from backtrader.plot.utils import tag_box_style
    >>> path = tag_box_style(0, 0, 1, 1, 0.1)
"""
from colorsys import hls_to_rgb as hls2rgb
from colorsys import rgb_to_hls as rgb2hls

import matplotlib.colors as mplcolors
import matplotlib.path as mplpath


def tag_box_style(x0, y0, width, height, mutation_size, mutation_aspect=1):
    """Create a box path with a tab/pointer.

    Given the location and size of the box, return the path of
    the box around it.

    Args:
        x0: X coordinate of box origin.
        y0: Y coordinate of box origin.
        width: Width of the box.
        height: Height of the box.
        mutation_size: Reference scale for the mutation.
        mutation_aspect: Aspect ratio for the mutation.

    Returns:
        A matplotlib Path object representing the box.
    """

    # Note that we are ignoring mutation_aspect. This is okay in general.
    mypad = 0.2
    pad = mutation_size * mypad

    # width and height with padding added.
    width, height = (
        width + 2.0 * pad,
        height + 2.0 * pad,
    )

    # boundary of the padded box
    x0, y0 = (
        x0 - pad,
        y0 - pad,
    )
    x1, y1 = x0 + width, y0 + height

    cp = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0 - pad, (y0 + y1) / 2.0), (x0, y0), (x0, y0)]

    com = [
        mplpath.Path.MOVETO,
        mplpath.Path.LINETO,
        mplpath.Path.LINETO,
        mplpath.Path.LINETO,
        mplpath.Path.LINETO,
        mplpath.Path.LINETO,
        mplpath.Path.CLOSEPOLY,
    ]

    path = mplpath.Path(cp, com)

    return path


def shade_color(color, percent):
    """Shade Color
    This color utility function allows the user to easily darken or
    lighten a color for plotting purposes.
    Parameters
    ----------
    color : string, list, hexvalue
        Any acceptable Matplotlib color value, such as
        'red', 'slategrey', '#FFEE11', (1,0,0)
    percent :  the amount by which to brighten or darken the color.
    Returns
    -------
    color : tuple of floats
        tuple representing converted rgb values
    """

    rgb = mplcolors.colorConverter.to_rgb(color)

    h, lightness, s = rgb2hls(*rgb)

    lightness *= 1 + float(percent) / 100

    lightness = min(1, lightness)
    lightness = max(0, lightness)

    r, g, b = hls2rgb(h, lightness, s)

    return r, g, b
