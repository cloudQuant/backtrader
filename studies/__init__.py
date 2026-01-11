#!/usr/bin/env python
"""Studies module for technical analysis patterns.

This module provides a collection of technical analysis studies and patterns
that extend beyond standard indicators. Studies are typically more complex
calculations or patterns that combine multiple indicators or implement
specific trading methodologies.

The studies module is organized into subdirectories:
- contrib/: Community-contributed studies and indicators

Studies in this module follow the backtrader pattern where they can be
used within strategies and automatically update during backtesting.

Example:
    >>> import backtrader as bt
    >>> # Studies are available via bt.studies namespace
    >>> # if registered through the contrib module

Note:
    This is a namespace package. Individual studies are imported from
    submodules and registered with the backtrader core.

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

from backtrader import Indicator
