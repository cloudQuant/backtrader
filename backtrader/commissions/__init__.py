#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
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
from ..comminfo import CommInfoBase


class CommInfo(CommInfoBase):
    pass  # clone of CommissionInfo but with xx% instead of 0.xx


class CommInfoFutures(CommInfoBase):
    params = (
        ('stocklike', False),
    )


class CommInfoFuturesPerc(CommInfoFutures):
    params = (
        ('commtype', CommInfoBase.COMM_PERC),
    )


class CommInfoFuturesFixed(CommInfoFutures):
    params = (
        ('commtype', CommInfoBase.COMM_FIXED),
    )


class CommInfoStocks(CommInfoBase):
    params = (
        ('stocklike', True),
    )


class CommInfoStocksPerc(CommInfoStocks):
    params = (
        ('commtype', CommInfoBase.COMM_PERC),
    )


class CommInfoStocksFixed(CommInfoStocks):
    params = (
        ('commtype', CommInfoBase.COMM_FIXED),
    )
