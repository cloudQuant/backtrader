#!/usr/bin/env python
"""Contributed Indicators Module - Community-contributed technical indicators.

This module contains technical indicators contributed by the community
that are not part of the standard indicator set.

Indicators:
    Vortex: Vortex Indicator for trend identification.

Example:
    Using contributed indicators:
    >>> cerebro.addindicator(bt.indicators.Vortex)
"""
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
import backtrader

from . import vortex as vortex

for name in vortex.__all__:
    setattr(backtrader.indicators, name, getattr(vortex, name))
