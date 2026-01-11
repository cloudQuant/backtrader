#!/usr/bin/env python
"""Community-contributed studies for backtrader.

This module contains technical analysis studies and indicators contributed
by the backtrader community. These studies implement various patterns,
indicators, and trading methodologies that extend the core backtrader
functionality.

The contrib module serves as a collection point for community submissions
before they may be promoted to the core indicators library. Studies here
may include:

* Pattern recognition indicators (e.g., fractals)
* Custom technical analysis methods
* Experimental or specialized indicators
* Ported indicators from other trading platforms

All studies in this module are automatically registered with the
backtrader core and made available via the bt.studies namespace.

Example:
    >>> import backtrader as bt
    >>> # After import, studies are available via bt.studies
    >>> # e.g., fractal indicators if registered

Registration:
    Studies are registered by defining __all__ in the study module and
    importing them here. The registration process adds them to bt.studies
    namespace for convenient access.

Note:
    These are community contributions and may not have the same level of
    testing or support as core indicators. Use at your own discretion and
    verify results before using in production trading systems.

Copyright (C) 2015-2020 Daniel Rodriguez

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import backtrader as bt

# Import fractal studies and register them with bt.studies
from . import fractal as fractal

# Register all fractal indicators in the bt.studies namespace
# This makes them accessible via bt.studies.<indicator_name>
for name in fractal.__all__:
    setattr(bt.studies, name, getattr(fractal, name))
